"""Decision engine: the deterministic authority on whether an opportunity exists."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.decision.engine import evaluate_upgrade
from app.decision.optimizer import find_three_passenger_opportunity
from app.models import (
    CostLimits,
    DecisionStatus,
    Observed,
    PageState,
    SnapshotSource,
    UpgradeDecision,
)
from tests.fixtures.snapshots import make_option, make_passengers, make_snapshot

FREE = CostLimits()  # cash_limit=0, miles_limit=0, passengers_target=3


# --- Scenario A ---------------------------------------------------------------
def test_three_business_free() -> None:
    decision = evaluate_upgrade(make_snapshot(), FREE)
    assert decision.status is DecisionStatus.OPPORTUNITY
    assert decision.passengers_target == 3
    assert decision.passengers_eligible == 3
    assert decision.business_seats_required == 3
    assert decision.business_seats_observed == 3
    assert decision.cash_cost == 0
    assert decision.miles_cost == 0
    assert decision.option_id == "OPT-1"
    assert decision.requires_human_confirmation is True
    assert decision.confidence >= 0.9


# --- Scenario B ---------------------------------------------------------------
def test_two_business_only() -> None:
    decision = evaluate_upgrade(make_snapshot(business_seats=2), FREE)
    assert decision.status is DecisionStatus.NO_OPPORTUNITY
    assert decision.business_seats_observed == 2
    assert "2" in decision.reason


def test_offer_covering_only_two_passengers_is_refused() -> None:
    snapshot = make_snapshot(options=[make_option(covers=2)])
    assert evaluate_upgrade(snapshot, FREE).status is DecisionStatus.NO_OPPORTUNITY


def test_three_individual_free_offers_are_not_combined() -> None:
    """Never optimise passengers separately: one offer must cover the whole group."""
    options = [make_option(covers=1, option_id=f"OPT-{i}") for i in range(3)]
    decision = evaluate_upgrade(make_snapshot(options=options), FREE)
    assert decision.status is DecisionStatus.NO_OPPORTUNITY


def test_one_passenger_not_eligible() -> None:
    snapshot = make_snapshot(passengers=make_passengers(3, eligible=2))
    decision = evaluate_upgrade(snapshot, FREE)
    assert decision.status is DecisionStatus.NO_OPPORTUNITY
    assert decision.passengers_eligible == 2


# --- Scenario C ---------------------------------------------------------------
def test_paid_upgrade() -> None:
    snapshot = make_snapshot(options=[make_option(cash=250)])
    decision = evaluate_upgrade(snapshot, FREE)
    assert decision.status is DecisionStatus.NO_OPPORTUNITY
    # The paid offer is reported (not hidden) but never selected.
    assert decision.rejected_options[0].cash_cost == 250
    assert decision.option_id is None


@pytest.mark.parametrize("price", ["0.01", "1", "10", "300", "1000"])
def test_any_cash_above_zero_is_refused(price: str) -> None:
    snapshot = make_snapshot(options=[make_option(cash=Decimal(price))])
    assert evaluate_upgrade(snapshot, FREE).status is DecisionStatus.NO_OPPORTUNITY


# --- Scenario D ---------------------------------------------------------------
def test_miles_upgrade() -> None:
    snapshot = make_snapshot(options=[make_option(miles=30_000)])
    decision = evaluate_upgrade(snapshot, FREE)
    assert decision.status is DecisionStatus.NO_OPPORTUNITY
    assert decision.rejected_options[0].miles_cost == 30_000


def test_miles_plus_cash_upgrade() -> None:
    option = make_option(cash=0, miles=15_000, mixed_cash=Decimal("90"))
    decision = evaluate_upgrade(make_snapshot(options=[option]), FREE)
    assert decision.status is DecisionStatus.NO_OPPORTUNITY


def test_limits_are_configurable_without_code_change() -> None:
    snapshot = make_snapshot(options=[make_option(cash=250)])
    relaxed = CostLimits(cash_limit=Decimal(300), miles_limit=0)
    assert evaluate_upgrade(snapshot, relaxed).status is DecisionStatus.OPPORTUNITY


# --- Scenario E ---------------------------------------------------------------
def test_no_business() -> None:
    snapshot = make_snapshot(business_available=False, business_seats=0, options=[])
    decision = evaluate_upgrade(snapshot, FREE)
    assert decision.status is DecisionStatus.NO_OPPORTUNITY
    assert decision.business_available is False


# --- Scenario F ---------------------------------------------------------------
def test_not_confirmed_by_airline() -> None:
    snapshot = make_snapshot(confirmed=False, source=SnapshotSource.MANUAL_ENTRY)
    decision = evaluate_upgrade(snapshot, FREE)
    assert decision.status is DecisionStatus.NO_OPPORTUNITY
    assert any("confirm" in issue.lower() for issue in decision.data_issues)


def test_llm_sourced_snapshot_never_opportunity() -> None:
    snapshot = make_snapshot(confirmed=True, source=SnapshotSource.LLM_INFERENCE)
    assert evaluate_upgrade(snapshot, FREE).status is DecisionStatus.NO_OPPORTUNITY


# --- Missing / inferred / conflicting data -------------------------------------
def test_missing_data() -> None:
    snapshot = make_snapshot(business_seats=None, business_available=None)
    decision = evaluate_upgrade(snapshot, FREE)
    assert decision.status is DecisionStatus.NO_OPPORTUNITY
    assert decision.business_seats_observed is None  # stays null, never estimated
    assert decision.business_available is None
    assert decision.confidence < 0.9


def test_unknown_price_is_not_free() -> None:
    snapshot = make_snapshot(options=[make_option(cash=None, miles=None)])
    decision = evaluate_upgrade(snapshot, FREE)
    assert decision.status is DecisionStatus.NO_OPPORTUNITY
    assert decision.cash_cost is None


def test_inferred_seat_count_is_not_proof() -> None:
    base = make_snapshot()
    snapshot = base.model_copy(
        update={"business_seats_visible": Observed[int].inferred(3, "probably more seats")}
    )
    decision = evaluate_upgrade(snapshot, FREE)
    assert decision.status is DecisionStatus.NO_OPPORTUNITY
    assert decision.business_seats_observed is None


def test_conflicting_data() -> None:
    # Business marked unavailable but 3 seats displayed: contradiction -> never guess.
    snapshot = make_snapshot(business_available=False, business_seats=3)
    decision = evaluate_upgrade(snapshot, FREE)
    assert decision.status is DecisionStatus.NO_OPPORTUNITY
    assert any("conflict" in issue.lower() for issue in decision.data_issues)


def test_conflicting_passenger_count() -> None:
    snapshot = make_snapshot(passengers_count=3, passengers=make_passengers(2))
    decision = evaluate_upgrade(snapshot, FREE)
    assert decision.status is DecisionStatus.NO_OPPORTUNITY
    assert any("conflict" in issue.lower() for issue in decision.data_issues)


def test_offer_marked_unavailable() -> None:
    snapshot = make_snapshot(options=[make_option(available=False)])
    assert evaluate_upgrade(snapshot, FREE).status is DecisionStatus.NO_OPPORTUNITY


# --- Page states requiring the human ------------------------------------------
@pytest.mark.parametrize(
    "state", [PageState.AUTHENTICATION_REQUIRED, PageState.HUMAN_VERIFICATION_REQUIRED]
)
def test_login_or_captcha_requires_user(state: PageState) -> None:
    decision = evaluate_upgrade(make_snapshot(page_state=state), FREE)
    assert decision.status is DecisionStatus.ACTION_REQUIRED
    assert decision.requires_human_confirmation is True


# --- Optimizer & schema --------------------------------------------------------
def test_optimizer_returns_single_group_option() -> None:
    snapshot = make_snapshot(
        options=[make_option(cash=100, option_id="PAID"), make_option(option_id="FREE")]
    )
    result = find_three_passenger_opportunity(snapshot, FREE)
    assert result.option is not None
    assert result.option.option_id == "FREE"
    assert [r.option_id for r in result.rejected] == ["PAID"]


def test_human_confirmation_required_flag() -> None:
    decision = evaluate_upgrade(make_snapshot(), FREE)
    assert decision.requires_human_confirmation is True


def test_decision_schema_rejects_extra_fields() -> None:
    payload = evaluate_upgrade(make_snapshot(), FREE).model_dump()
    payload["upgrade_executed"] = True
    with pytest.raises(ValidationError):
        UpgradeDecision.model_validate(payload)
