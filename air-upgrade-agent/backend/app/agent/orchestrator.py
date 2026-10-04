"""LLM Orchestrator (Microsoft Foundry / Azure OpenAI).

The LLM explains, reformulates and handles ambiguity - it is NOT the authority
on availability. Guardrails:

* it receives an allow-listed, anonymised view of the snapshot (no names, no
  PNR, no tickets, no screenshots, no credentials);
* its output must match :class:`LLMDecisionPayload` exactly, else it is refused;
* it may only keep or *lower* the deterministic status, never raise it;
* every number (seats, eligible passengers, cash, miles) must equal the
  observed value - in particular it can never turn ``null`` into a value.

Without Azure configuration the deterministic engine works alone.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any, Protocol

from pydantic import ValidationError

from app.config import Settings
from app.decision.engine import evaluate_upgrade
from app.models import (
    BookingSnapshot,
    CostLimits,
    DecisionStatus,
    LLMDecisionPayload,
    UpgradeDecision,
)
from app.models.decision import STATUS_RANK
from app.security.privacy import PrivacyManager, get_privacy_manager

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu es l'assistant d'analyse d'AIR UPGRADE AGENT.
Tu reçois une observation anonymisée d'une réservation et la décision du moteur déterministe.
Règles impératives :
- La disponibilité provient UNIQUEMENT de l'observation. Une valeur null reste null.
- Ne transforme jamais une inférence en donnée observée.
- Tu peux garder le statut du moteur ou le rendre plus prudent, jamais plus optimiste.
- Recopie exactement les valeurs numériques observées (sièges, passagers éligibles, coûts).
- Toute action réelle exige une confirmation humaine.
- N'invente aucune API, aucun contournement, aucune manipulation de billet ou de carte d'embarquement.
Réponds uniquement avec le JSON conforme au schéma demandé, en français, de façon concise."""


class LLMClient(Protocol):
    async def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> str: ...


class AzureOpenAIClient:
    """Azure OpenAI deployment (works with a Microsoft Foundry project endpoint)."""

    def __init__(self, settings: Settings) -> None:
        from openai import AsyncAzureOpenAI

        assert settings.azure_openai_api_key is not None
        self._client = AsyncAzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint or "",
            api_key=settings.azure_openai_api_key.get_secret_value(),
            api_version=settings.azure_openai_api_version,
        )
        self._deployment = settings.azure_openai_deployment or ""

    async def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
        response = await self._client.chat.completions.create(
            model=self._deployment,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "UpgradeDecision", "schema": schema, "strict": True},
            },
            temperature=0,
        )
        return response.choices[0].message.content or ""


def _strict_schema() -> dict[str, Any]:
    """JSON schema in the form required by structured outputs (all fields required)."""
    schema = LLMDecisionPayload.model_json_schema()
    schema["additionalProperties"] = False
    schema["required"] = list(schema["properties"])
    return schema


def build_llm_view(
    snapshot: BookingSnapshot, decision: UpgradeDecision, limits: CostLimits
) -> dict[str, Any]:
    """Allow-list: only what is needed to explain the decision."""
    flight = snapshot.flight
    return {
        "flight": flight.flight_number if flight else None,
        "route": f"{flight.origin}-{flight.destination}" if flight else None,
        "page_state": snapshot.page_state.value,
        "confirmed_by_airline": snapshot.confirmed_by_airline,
        "passengers": [
            {
                "id": p.anonymized_id,
                "cabin": p.current_cabin.model_dump(mode="json"),
                "eligibility": p.eligibility_status.model_dump(mode="json"),
            }
            for p in snapshot.passengers
        ],
        "business_available": snapshot.business_available.model_dump(mode="json"),
        "business_seats_visible": snapshot.business_seats_visible.model_dump(mode="json"),
        "checkin_status": snapshot.checkin_status.model_dump(mode="json"),
        "upgrade_options": [
            {
                "option_id": o.option_id,
                "cabin": o.cabin.value,
                "cash_price": None if o.total_cash is None else float(o.total_cash),
                "miles_price": o.miles_price,
                "passengers_covered": o.passengers_covered,
                "availability": o.availability,
                "provenance": o.provenance.value,
            }
            for o in snapshot.upgrade_options
        ],
        "observed_messages": snapshot.observed_messages,
        "limits": {
            "cash_limit": float(limits.cash_limit),
            "miles_limit": limits.miles_limit,
            "passengers_target": limits.passengers_target,
        },
        "engine_decision": {
            "status": decision.status.value,
            "reason": decision.reason,
            "passengers_eligible": decision.passengers_eligible,
            "business_seats_observed": decision.business_seats_observed,
            "cash_cost": None if decision.cash_cost is None else float(decision.cash_cost),
            "miles_cost": decision.miles_cost,
        },
    }


def apply_guardrails(engine: UpgradeDecision, llm: LLMDecisionPayload) -> UpgradeDecision | None:
    """Merge the LLM output into the engine decision, or return None if it is unsafe."""
    if STATUS_RANK[llm.status] > STATUS_RANK[engine.status]:
        return None  # more optimistic than the observation allows
    llm_cash = None if llm.cash_cost is None else Decimal(str(llm.cash_cost))
    if (
        llm.passengers_target != engine.passengers_target
        or llm.passengers_eligible != engine.passengers_eligible
        or llm.business_seats_observed != engine.business_seats_observed
        or llm.miles_cost != engine.miles_cost
        or llm_cash != engine.cash_cost
    ):
        return None  # altered or invented numbers (e.g. null -> 3)
    if llm.status is not DecisionStatus.NO_OPPORTUNITY and not llm.requires_human_confirmation:
        return None
    privacy = get_privacy_manager()
    downgraded = llm.status is not engine.status
    return engine.model_copy(
        update={
            "status": llm.status,
            "reason": privacy.sanitize_text(llm.reason),
            "recommendation": privacy.sanitize_text(llm.recommendation),
            "option_id": None
            if downgraded and llm.status is not DecisionStatus.OPPORTUNITY
            else engine.option_id,
            "requires_human_confirmation": engine.requires_human_confirmation
            or llm.status is not DecisionStatus.NO_OPPORTUNITY,
            "decided_by": "DETERMINISTIC_ENGINE+LLM",
        }
    )


class LLMOrchestrator:
    def __init__(
        self, client: LLMClient | None = None, privacy: PrivacyManager | None = None
    ) -> None:
        self.client = client
        self.privacy = privacy or get_privacy_manager()
        self.last_payload: dict[str, Any] | None = None  # for audits/tests: exactly what was sent

    @classmethod
    def from_settings(cls, settings: Settings) -> LLMOrchestrator:
        if not settings.azure_configured:
            return cls(None)
        try:
            return cls(AzureOpenAIClient(settings))
        except Exception:
            logger.warning("Azure OpenAI client unavailable: deterministic mode only")
            return cls(None)

    @property
    def enabled(self) -> bool:
        return self.client is not None

    async def decide(self, snapshot: BookingSnapshot, limits: CostLimits) -> UpgradeDecision:
        engine = evaluate_upgrade(snapshot, limits)
        if self.client is None:
            return engine
        payload = self.privacy.sanitize_llm_payload(build_llm_view(snapshot, engine, limits))
        self.last_payload = payload
        try:
            raw = await self.client.complete_json(
                SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False), _strict_schema()
            )
            parsed = LLMDecisionPayload.model_validate_json(raw)
        except ValidationError:
            logger.warning("LLM output refused: not conforming to the UpgradeDecision schema")
            return engine.model_copy(
                update={"data_issues": [*engine.data_issues, "LLM_OUTPUT_REJECTED: schema"]}
            )
        except Exception as exc:
            logger.warning("LLM unavailable (%s): deterministic decision kept", type(exc).__name__)
            return engine
        merged = apply_guardrails(engine, parsed)
        if merged is None:
            logger.warning("LLM output refused by guardrails")
            return engine.model_copy(
                update={"data_issues": [*engine.data_issues, "LLM_OUTPUT_REJECTED: guardrails"]}
            )
        return merged
