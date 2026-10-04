"""ObservationEngine parsing + every MOCK AIR FRANCE scenario through the decision engine."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.booking.observation import (
    parse_availability,
    parse_cabin,
    parse_checkin,
    parse_miles,
    parse_money,
)
from app.booking.providers.mock_airfrance import MockAirFrance, MockAirFranceProvider
from app.decision.engine import evaluate_upgrade
from app.models import (
    Cabin,
    CheckinStatus,
    CostLimits,
    DecisionStatus,
    PageState,
    Provenance,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("750,00 €", Decimal("750.00")),
        ("1 250,50 €", Decimal("1250.50")),
        ("EUR 90", Decimal(90)),
        ("Gratuit", Decimal(0)),
        ("0 €", Decimal(0)),
        ("15 000 Miles + 90 €", Decimal(90)),
        ("Prix sur demande", None),
        (None, None),
    ],
)
def test_parse_money(text: str | None, expected: Decimal | None) -> None:
    assert parse_money(text) == expected


def test_parsers() -> None:
    assert parse_miles("30 000 Miles") == 30_000
    assert parse_miles("0 €") is None
    assert parse_cabin("Économie") is Cabin.ECONOMY
    assert parse_cabin("Business") is Cabin.BUSINESS
    assert parse_cabin("???") is None
    assert parse_availability("Cabine Business indisponible") is False
    assert parse_availability("Disponible") is True
    assert parse_availability("Peut-être") is None
    assert parse_checkin("Enregistrement fermé") is CheckinStatus.CLOSED
    assert parse_checkin("L'enregistrement ouvrira 30 h avant le départ") is CheckinStatus.NOT_OPEN
    assert parse_checkin("Enregistrement ouvert") is CheckinStatus.OPEN


async def snapshot_for(scenario: str):  # type: ignore[no-untyped-def]
    return await MockAirFranceProvider(MockAirFrance(scenario)).take_snapshot()


async def test_snapshot_contains_no_personal_data() -> None:
    snap = await snapshot_for("free_upgrade_3_business")
    dumped = snap.model_dump_json()
    for pii in ("TEST123", "TESTDIOP", "Awa", "0570000000001"):
        assert pii not in dumped
    assert snap.anonymized_booking_id == "PNR_****123"
    assert [p.anonymized_id for p in snap.passengers] == [
        "PASSENGER_001",
        "PASSENGER_002",
        "PASSENGER_003",
    ]


async def test_unknown_values_stay_null() -> None:
    mock = MockAirFrance("no_upgrade")
    mock._page.business_seats_text = None
    mock._page.business_availability_text = "Information indisponible pour le moment???"
    snap = await MockAirFranceProvider(mock).take_snapshot()
    assert snap.business_seats_visible.value is None
    assert snap.business_seats_visible.provenance is Provenance.UNKNOWN


EXPECTED = {
    "free_upgrade_3_business": DecisionStatus.OPPORTUNITY,  # A
    "two_business_available": DecisionStatus.NO_OPPORTUNITY,  # B
    "paid_upgrade": DecisionStatus.NO_OPPORTUNITY,  # C
    "miles_upgrade": DecisionStatus.NO_OPPORTUNITY,  # D
    "business_unavailable": DecisionStatus.NO_OPPORTUNITY,  # E
    "not_confirmed_by_airline": DecisionStatus.NO_OPPORTUNITY,  # F
    "economy_only": DecisionStatus.NO_OPPORTUNITY,
    "economy_and_business": DecisionStatus.NO_OPPORTUNITY,
    "miles_cash_upgrade": DecisionStatus.NO_OPPORTUNITY,
    "no_upgrade": DecisionStatus.NO_OPPORTUNITY,
    "checkin_closed": DecisionStatus.NO_OPPORTUNITY,
    "checkin_not_open": DecisionStatus.NO_OPPORTUNITY,
    "checkin_open": DecisionStatus.NO_OPPORTUNITY,
    "conflicting_data": DecisionStatus.NO_OPPORTUNITY,
    "login_required": DecisionStatus.ACTION_REQUIRED,
    "captcha": DecisionStatus.ACTION_REQUIRED,
}


def test_every_mock_scenario_is_covered() -> None:
    assert set(MockAirFrance().scenarios) == set(EXPECTED)


@pytest.mark.parametrize(("scenario", "expected"), sorted(EXPECTED.items()))
async def test_mock_scenarios(scenario: str, expected: DecisionStatus) -> None:
    decision = evaluate_upgrade(await snapshot_for(scenario), CostLimits())
    assert decision.status is expected, decision.reason


async def test_paid_offer_is_reported_with_its_price() -> None:
    decision = evaluate_upgrade(await snapshot_for("paid_upgrade"), CostLimits())
    assert decision.cash_cost == Decimal(750)
    assert "payante" in decision.recommendation


async def test_checkin_states() -> None:
    assert (await snapshot_for("checkin_closed")).checkin_status.value is CheckinStatus.CLOSED
    assert (await snapshot_for("checkin_open")).checkin_status.value is CheckinStatus.OPEN
    assert (await snapshot_for("login_required")).page_state is PageState.AUTHENTICATION_REQUIRED
