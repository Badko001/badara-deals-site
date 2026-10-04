"""Three-passenger optimizer.

The group is evaluated as a single unit: one official offer must cover *all*
target passengers at once. Individual per-passenger offers are never combined
(the airline could accept two and refuse the third, splitting the group).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.models import (
    BookingSnapshot,
    Cabin,
    CostLimits,
    Eligibility,
    Provenance,
    RejectedOption,
    SnapshotSource,
    UpgradeOption,
)

# Sources whose content comes from the airline's own system.
AIRLINE_SOURCES = frozenset({SnapshotSource.AIR_FRANCE_WEB, SnapshotSource.MOCK_AIR_FRANCE})


@dataclass(frozen=True)
class OpportunityResult:
    option: UpgradeOption | None
    rejected: list[RejectedOption] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    @property
    def is_opportunity(self) -> bool:
        return self.option is not None and not self.blockers


def count_eligible(snapshot: BookingSnapshot) -> int | None:
    """Passengers whose eligibility was *observed* as ELIGIBLE (None if none observed)."""
    observed = [
        p.eligibility_status for p in snapshot.passengers if p.eligibility_status.is_observed
    ]
    if not observed:
        return None
    return sum(1 for e in observed if e.value is Eligibility.ELIGIBLE)


def option_rejection_reason(option: UpgradeOption, limits: CostLimits) -> str | None:
    """Return why an offer cannot be used for the group, or None if it is valid."""
    target = limits.passengers_target
    if option.cabin is not Cabin.BUSINESS:
        return f"Offre vers {option.cabin.value}, pas Business"
    if option.provenance is not Provenance.OBSERVED:
        return "Offre non observée sur la page officielle (inférence)"
    if option.availability is not True:
        return "Offre indisponible ou disponibilité non affichée"
    if option.passengers_covered is None:
        return "Nombre de passagers couverts par l'offre non affiché"
    if option.passengers_covered < target:
        return f"L'offre ne couvre que {option.passengers_covered} passager(s) sur {target}"
    total_cash = option.total_cash
    if total_cash is None:
        return "Prix en euros non affiché"
    if option.miles_price is None:
        return "Coût en Miles non affiché"
    if total_cash > limits.cash_limit:
        return f"Coût {total_cash} € supérieur à la limite de {limits.cash_limit} €"
    if option.miles_price > limits.miles_limit:
        return (
            f"Coût {option.miles_price} Miles supérieur à la limite de {limits.miles_limit} Miles"
        )
    return None


def group_blockers(snapshot: BookingSnapshot, limits: CostLimits) -> list[str]:
    """Group-level conditions that must all hold, whatever the offer."""
    target = limits.passengers_target
    blockers: list[str] = []

    if not snapshot.confirmed_by_airline or snapshot.source not in AIRLINE_SOURCES:
        blockers.append("Informations non confirmées par le système de la compagnie")

    available = snapshot.business_available.observed_value
    if available is None:
        blockers.append("Disponibilité Business non observée")
    elif available is False:
        blockers.append("Cabine Business indisponible")

    seats = snapshot.business_seats_visible.observed_value
    if seats is None:
        blockers.append("Nombre de sièges Business visibles non observé")
    elif seats < target:
        blockers.append(f"Seulement {seats} siège(s) Business visible(s) pour {target} passagers")

    if len(snapshot.passengers) < target:
        blockers.append(
            f"{len(snapshot.passengers)} passager(s) visible(s) dans la réservation, {target} requis"
        )
    eligible = count_eligible(snapshot)
    if eligible is None:
        blockers.append("Éligibilité des passagers non observée")
    elif eligible < target:
        blockers.append(f"Seulement {eligible} passager(s) éligible(s) sur {target}")
    return blockers


def find_three_passenger_opportunity(
    snapshot: BookingSnapshot, limits: CostLimits
) -> OpportunityResult:
    """Find ONE official offer that upgrades the whole group within the limits.

    Rule: seats_observed >= target AND cash <= cash_limit AND miles <= miles_limit
    AND all target passengers eligible -> opportunity. Otherwise no opportunity.
    """
    blockers = group_blockers(snapshot, limits)
    valid: list[UpgradeOption] = []
    rejected: list[RejectedOption] = []
    for option in snapshot.upgrade_options:
        reason = option_rejection_reason(option, limits)
        if reason is None:
            valid.append(option)
        else:
            rejected.append(
                RejectedOption(
                    option_id=option.option_id,
                    reason=reason,
                    cash_cost=option.total_cash,
                    miles_cost=option.miles_price,
                )
            )
    if not valid:
        blockers.append("Aucune offre officielle valide couvrant tout le groupe")
        return OpportunityResult(option=None, rejected=rejected, blockers=blockers)

    # Cheapest first; prefer offers with an official action button.
    def cost_key(o: UpgradeOption) -> tuple[Decimal, int, int]:
        return (o.total_cash or Decimal(0), o.miles_price or 0, 0 if o.actionable else 1)

    best = min(valid, key=cost_key)
    return OpportunityResult(option=best, rejected=rejected, blockers=blockers)
