"""LLM orchestrator: anonymised payload, strict schema, guardrails."""

from __future__ import annotations

import json
from typing import Any

from app.agent.orchestrator import LLMOrchestrator
from app.booking.providers.mock_airfrance import MockAirFrance, MockAirFranceProvider
from app.models import CostLimits, DecisionStatus
from tests.fixtures.snapshots import make_snapshot


class FakeLLM:
    def __init__(self, response: dict[str, Any] | str) -> None:
        self.response = response
        self.calls: list[str] = []

    async def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
        self.calls.append(user)
        return self.response if isinstance(self.response, str) else json.dumps(self.response)


def _payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "status": "NO_OPPORTUNITY",
        "reason": "Seulement 2 sièges visibles.",
        "passengers_target": 3,
        "passengers_eligible": 3,
        "business_seats_observed": 2,
        "cash_cost": 0,
        "miles_cost": 0,
        "recommendation": "Continuer la surveillance.",
        "requires_human_confirmation": False,
    }
    base.update(overrides)
    return base


async def test_no_azure_means_deterministic_only() -> None:
    decision = await LLMOrchestrator(None).decide(make_snapshot(), CostLimits())
    assert decision.status is DecisionStatus.OPPORTUNITY
    assert decision.decided_by == "DETERMINISTIC_ENGINE"


async def test_llm_cannot_upgrade_a_no_opportunity() -> None:
    llm = FakeLLM(_payload(status="OPPORTUNITY", requires_human_confirmation=True))
    decision = await LLMOrchestrator(llm).decide(make_snapshot(business_seats=2), CostLimits())
    assert decision.status is DecisionStatus.NO_OPPORTUNITY
    assert "LLM_OUTPUT_REJECTED: guardrails" in decision.data_issues


async def test_llm_cannot_turn_null_into_value() -> None:
    llm = FakeLLM(_payload(business_seats_observed=3, reason="Il y a sûrement 3 sièges."))
    decision = await LLMOrchestrator(llm).decide(make_snapshot(business_seats=None), CostLimits())
    assert decision.business_seats_observed is None
    assert "LLM_OUTPUT_REJECTED: guardrails" in decision.data_issues


async def test_non_conforming_output_is_refused() -> None:
    llm = FakeLLM({"status": "OPPORTUNITY", "upgrade": "done"})
    decision = await LLMOrchestrator(llm).decide(make_snapshot(business_seats=2), CostLimits())
    assert decision.status is DecisionStatus.NO_OPPORTUNITY
    assert "LLM_OUTPUT_REJECTED: schema" in decision.data_issues


async def test_llm_may_explain_and_be_more_conservative() -> None:
    llm = FakeLLM(
        _payload(
            status="ACTION_REQUIRED",
            business_seats_observed=3,
            reason="Message ambigu sur la page.",
            recommendation="Vérifiez vous-même.",
            requires_human_confirmation=True,
        )
    )
    decision = await LLMOrchestrator(llm).decide(make_snapshot(), CostLimits())
    assert decision.status is DecisionStatus.ACTION_REQUIRED
    assert decision.option_id is None
    assert decision.decided_by == "DETERMINISTIC_ENGINE+LLM"


async def test_no_personal_data_sent_to_llm() -> None:
    llm = FakeLLM(
        _payload(status="OPPORTUNITY", business_seats_observed=3, requires_human_confirmation=True)
    )
    snapshot = await MockAirFranceProvider(MockAirFrance("free_upgrade_3_business")).take_snapshot()
    orchestrator = LLMOrchestrator(llm)
    await orchestrator.decide(snapshot, CostLimits())
    sent = llm.calls[0]
    for pii in ("TEST123", "Awa", "TESTDIOP", "Moussa", "0570000000001", "internal_id"):
        assert pii not in sent, pii
    assert "PASSENGER_001" in sent
    assert orchestrator.last_payload is not None


async def test_llm_failure_falls_back_to_engine() -> None:
    class Broken:
        async def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
            raise TimeoutError

    decision = await LLMOrchestrator(Broken()).decide(make_snapshot(), CostLimits())
    assert decision.status is DecisionStatus.OPPORTUNITY
