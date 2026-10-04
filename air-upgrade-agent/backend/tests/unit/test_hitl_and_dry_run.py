"""Human-in-the-loop, DRY_RUN and real-action verification (on MOCK AIR FRANCE)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from app.booking.providers.mock_airfrance import MockAirFranceProvider
from app.errors import HumanConfirmationRequired
from app.models.actions import ExecutionStatus, HumanConfirmation
from app.models.domain import utcnow
from app.services.container import Container
from tests.conftest import make_container
from tests.fixtures.snapshots import make_option


async def _opportunity(container: Container) -> str:
    result = await container.monitoring.check_once()
    assert result.decision.status.value == "OPPORTUNITY"
    pending = container.confirmations.current_pending()
    assert pending is not None
    return pending.confirmation_id


async def test_human_confirmation_required() -> None:
    container = make_container(dry_run=False)
    assert container.mock is not None
    option = make_option(option_id="UPG-BUS-FREE")

    # 1. The provider refuses without a HumanConfirmation...
    with pytest.raises(HumanConfirmationRequired):
        await container.provider.request_upgrade(option, None)
    # 2. ...with an expired one...
    past = utcnow() - timedelta(minutes=1)
    expired = HumanConfirmation(
        confirmation_id="x",
        option_id=option.option_id,
        snapshot_id="s",
        max_cash=Decimal(0),
        max_miles=0,
        passengers=3,
        confirmed_at=past,
        expires_at=past,
    )
    with pytest.raises(HumanConfirmationRequired):
        await container.provider.request_upgrade(option, expired)
    # 3. ...and an unknown confirmation id cannot be confirmed.
    with pytest.raises(HumanConfirmationRequired):
        await container.executor.confirm_and_execute("forged-id", container.runtime.get_limits())
    assert container.mock.accepted_offers == []


async def test_decline_does_nothing() -> None:
    container = make_container(dry_run=False)
    assert container.mock is not None
    confirmation_id = await _opportunity(container)
    container.executor.decline(confirmation_id)
    assert container.mock.accepted_offers == []
    with pytest.raises(HumanConfirmationRequired):  # a declined request cannot be confirmed later
        await container.executor.confirm_and_execute(
            confirmation_id, container.runtime.get_limits()
        )
    assert container.mock.accepted_offers == []


async def test_dry_run() -> None:
    container = make_container(dry_run=True)
    assert container.mock is not None
    confirmation_id = await _opportunity(container)
    result = await container.executor.confirm_and_execute(
        confirmation_id, container.runtime.get_limits()
    )
    assert result.status is ExecutionStatus.DRY_RUN_SIMULATED
    assert container.mock.accepted_offers == []  # nothing changed on the airline side
    snap = await container.provider.take_snapshot()
    assert all(p.current_cabin.value.value == "ECONOMY" for p in snap.passengers)  # type: ignore[union-attr]


async def test_confirmation_is_single_use() -> None:
    container = make_container(dry_run=True)
    confirmation_id = await _opportunity(container)
    await container.executor.confirm_and_execute(confirmation_id, container.runtime.get_limits())
    with pytest.raises(HumanConfirmationRequired):
        await container.executor.confirm_and_execute(
            confirmation_id, container.runtime.get_limits()
        )


async def test_real_mode_success_is_verified_by_airline() -> None:
    container = make_container(dry_run=False)
    assert container.mock is not None
    confirmation_id = await _opportunity(container)
    result = await container.executor.confirm_and_execute(
        confirmation_id, container.runtime.get_limits()
    )
    assert result.status is ExecutionStatus.CONFIRMED_BY_AIRLINE
    assert container.mock.accepted_offers == ["UPG-BUS-FREE"]


async def test_offer_changed_after_alert_aborts() -> None:
    container = make_container(dry_run=False)
    assert container.mock is not None
    confirmation_id = await _opportunity(container)
    container.mock.set_scenario("paid_upgrade")  # price changed before the user clicked
    result = await container.executor.confirm_and_execute(
        confirmation_id, container.runtime.get_limits()
    )
    assert result.status is ExecutionStatus.ABORTED
    assert container.mock.accepted_offers == []


async def test_airline_not_confirming_is_reported_honestly() -> None:
    container = make_container(dry_run=False)
    assert isinstance(container.provider, MockAirFranceProvider)
    confirmation_id = await _opportunity(container)
    container.provider.mock.accept_offer = lambda offer_id: True  # type: ignore[method-assign]
    result = await container.executor.confirm_and_execute(
        confirmation_id, container.runtime.get_limits()
    )
    assert result.status is ExecutionStatus.NOT_CONFIRMED_BY_AIRLINE
