"""Deterministic decision engine - the final authority on availability.

The LLM may explain a decision or make it *more* conservative, never the reverse.
"""

from __future__ import annotations

from decimal import Decimal

from app.decision.optimizer import count_eligible, find_three_passenger_opportunity
from app.models import (
    BookingSnapshot,
    CostLimits,
    DecisionStatus,
    PageState,
    RejectedOption,
    UpgradeDecision,
    UpgradeOption,
)

_PAGE_STATE_MESSAGES: dict[PageState, str] = {
    PageState.AUTHENTICATION_REQUIRED: (
        "Session expirée : connectez-vous vous-même dans le navigateur isolé."
    ),
    PageState.HUMAN_VERIFICATION_REQUIRED: (
        "Vérification anti-robot affichée : elle doit être résolue par vous, jamais contournée."
    ),
    PageState.BOOKING_NOT_FOUND: "Réservation introuvable dans votre espace : vérifiez-la.",
    PageState.UNEXPECTED: "Page inattendue : l'agent s'est arrêté sans rien deviner.",
}


def detect_conflicts(snapshot: BookingSnapshot) -> list[str]:
    """Contradictions between observed values. Any conflict blocks the decision."""
    issues: list[str] = []
    available = snapshot.business_available.observed_value
    seats = snapshot.business_seats_visible.observed_value
    if available is False and seats:
        issues.append(
            f"CONFLICT_BUSINESS_AVAILABILITY: Business indiquée indisponible mais {seats} siège(s) affiché(s)"
        )
    if available is True and seats == 0:
        issues.append(
            "CONFLICT_BUSINESS_AVAILABILITY: Business indiquée disponible mais 0 siège affiché"
        )
    count = snapshot.passengers_count.observed_value
    if count is not None and snapshot.passengers and count != len(snapshot.passengers):
        issues.append(
            f"CONFLICT_PASSENGER_COUNT: {count} passagers annoncés, {len(snapshot.passengers)} listés"
        )
    ids = [o.option_id for o in snapshot.upgrade_options]
    if len(ids) != len(set(ids)):
        issues.append("CONFLICT_DUPLICATE_OPTIONS: identifiants d'offre dupliqués")
    return issues


def _data_quality_issues(snapshot: BookingSnapshot) -> list[str]:
    issues: list[str] = []
    if not snapshot.confirmed_by_airline:
        issues.append("NOT_CONFIRMED_BY_AIRLINE: données non confirmées par la compagnie")
    for name in ("business_available", "business_seats_visible", "passengers_count"):
        value = getattr(snapshot, name)
        if not value.is_observed:
            issues.append(f"NOT_OBSERVED: {name} ({value.provenance.value})")
    return issues


def _critical_coverage(snapshot: BookingSnapshot) -> float:
    checks = [
        snapshot.business_available.is_observed,
        snapshot.business_seats_visible.is_observed,
        snapshot.passengers_count.is_observed,
        count_eligible(snapshot) is not None,
        snapshot.confirmed_by_airline,
    ]
    return sum(checks) / len(checks)


def _display_option(
    snapshot: BookingSnapshot, chosen: UpgradeOption | None
) -> UpgradeOption | None:
    """Offer whose costs are shown to the user: the chosen one, else the cheapest observed."""
    if chosen is not None:
        return chosen
    priced = [o for o in snapshot.upgrade_options if o.total_cash is not None]
    if not priced:
        return None
    return min(priced, key=lambda o: (o.total_cash or Decimal(0), o.miles_price or 0))


def evaluate_upgrade(
    snapshot: BookingSnapshot, limits: CostLimits | None = None
) -> UpgradeDecision:
    limits = limits or CostLimits()
    target = limits.passengers_target
    seats = snapshot.business_seats_visible.observed_value
    available = snapshot.business_available.observed_value
    eligible = count_eligible(snapshot)

    def build(
        status: DecisionStatus,
        reason: str,
        recommendation: str,
        confidence: float,
        *,
        option: UpgradeOption | None = None,
        rejected: list[RejectedOption] | None = None,
        issues: list[str] | None = None,
    ) -> UpgradeDecision:
        shown = _display_option(snapshot, option)
        return UpgradeDecision(
            status=status,
            reason=reason,
            passengers_target=target,
            passengers_eligible=eligible,
            business_available=available,
            business_seats_required=target,
            business_seats_observed=seats,
            cash_cost=shown.total_cash if shown else None,
            miles_cost=shown.miles_price if shown else None,
            recommendation=recommendation,
            confidence=round(confidence, 2),
            requires_human_confirmation=status is not DecisionStatus.NO_OPPORTUNITY,
            option_id=option.option_id if option else None,
            rejected_options=rejected or [],
            data_issues=issues or [],
            snapshot_id=snapshot.snapshot_id,
        )

    # 1. The page itself needs the human (login, CAPTCHA, wrong page): stop, don't guess.
    if snapshot.page_state is not PageState.BOOKING_VISIBLE:
        message = _PAGE_STATE_MESSAGES[snapshot.page_state]
        return build(
            DecisionStatus.ACTION_REQUIRED,
            reason=f"Page dans l'état {snapshot.page_state.value}",
            recommendation=message,
            confidence=1.0,
            issues=[f"PAGE_STATE: {snapshot.page_state.value}"],
        )

    issues = _data_quality_issues(snapshot)
    conflicts = detect_conflicts(snapshot)
    result = find_three_passenger_opportunity(snapshot, limits)

    # 2. Contradictory observations: never pick a side.
    if conflicts:
        return build(
            DecisionStatus.NO_OPPORTUNITY,
            reason="Données contradictoires observées : " + "; ".join(conflicts),
            recommendation="Aucune action. Revérifier lors du prochain contrôle.",
            confidence=0.3,
            rejected=result.rejected,
            issues=conflicts + issues,
        )

    # 3. A single official offer covers the whole group within limits.
    if result.is_opportunity and result.option is not None:
        option = result.option
        cost = f"{option.total_cash} € / {option.miles_price} Miles"
        if not option.actionable:
            return build(
                DecisionStatus.ACTION_REQUIRED,
                reason=f"Offre Business valide pour {target} passagers ({cost}) sans bouton officiel",
                recommendation=(
                    "L'offre doit être acceptée par vous via le canal officiel indiqué par la compagnie."
                ),
                confidence=0.85,
                option=option,
                rejected=result.rejected,
                issues=issues,
            )
        return build(
            DecisionStatus.OPPORTUNITY,
            reason=(
                f"Offre officielle Business pour {target} passagers simultanément, "
                f"{seats} sièges visibles, coût {cost}"
            ),
            recommendation="Opportunité réelle détectée. Confirmation humaine requise avant toute action.",
            confidence=1.0 if not issues else 0.9,
            option=option,
            rejected=result.rejected,
            issues=issues,
        )

    # 4. Otherwise: no opportunity, with the precise reasons.
    reasons = result.blockers + [f"{r.option_id}: {r.reason}" for r in result.rejected]
    paid = [r for r in result.rejected if (r.cash_cost or 0) > 0 or (r.miles_cost or 0) > 0]
    recommendation = "Aucune action. La surveillance continue."
    if paid:
        recommendation = (
            "Offre(s) payante(s) observée(s) hors limites : signalée(s), non exécutée(s). "
            "La surveillance continue."
        )
    return build(
        DecisionStatus.NO_OPPORTUNITY,
        reason="; ".join(reasons) or "Aucune offre observée",
        recommendation=recommendation,
        confidence=0.5 + 0.5 * _critical_coverage(snapshot),
        rejected=result.rejected,
        issues=issues,
    )
