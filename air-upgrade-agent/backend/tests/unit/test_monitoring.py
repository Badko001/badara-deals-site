"""MonitoringEngine: change detection, notifications, cadence and rate limiting."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.monitoring.engine import ChangeType, MonitoringStatus, RateLimited
from app.notifications.service import NotificationEvent
from tests.conftest import make_container


async def test_monitoring_change() -> None:
    container = make_container("checkin_not_open")
    assert container.mock is not None
    mon = container.monitoring

    first = await mon.check_once()
    assert first.decision.status.value == "NO_OPPORTUNITY"
    assert first.changes == []

    container.mock.set_scenario("checkin_open")
    second = await mon.check_once()
    assert {c.type for c in second.changes} >= {ChangeType.CHECKIN_OPENED, ChangeType.SEATS_CHANGED}
    assert [n.event for n in second.notifications] == [NotificationEvent.CHECKIN_OPEN]

    container.mock.set_scenario("paid_upgrade")
    third = await mon.check_once()
    assert ChangeType.NEW_UPGRADE_OPTION in {c.type for c in third.changes}
    assert third.notifications == []  # a paid offer is reported in the dashboard, not alerted

    container.mock.set_scenario("free_upgrade_3_business")
    fourth = await mon.check_once()
    assert [n.event for n in fourth.notifications] == [NotificationEvent.OPPORTUNITY_FOUND]
    assert "3 passagers" in fourth.notifications[0].message
    assert "0 € / 0 Miles" in fourth.notifications[0].message
    assert container.confirmations.current_pending() is not None
    assert mon.state.status is MonitoringStatus.OPPORTUNITY_FOUND

    container.mock.set_scenario("two_business_available")
    fifth = await mon.check_once()
    assert [n.event for n in fifth.notifications] == [NotificationEvent.NO_LONGER_AVAILABLE]
    assert container.confirmations.current_pending() is None


async def test_action_required_notification() -> None:
    container = make_container("login_required")
    result = await container.monitoring.check_once()
    assert [n.event for n in result.notifications] == [NotificationEvent.ACTION_REQUIRED]


async def test_rate_limit_for_real_airline() -> None:
    container = make_container()
    container.provider.enforce_rate_limit = True  # behave like the real site
    await container.monitoring.check_once()
    with pytest.raises(RateLimited):
        await container.monitoring.check_once()


def test_intervals_are_clamped() -> None:
    s = Settings(
        poll_interval_seconds=5,
        minimum_check_interval=60,
        maximum_check_interval=600,
        _env_file=None,
    )  # type: ignore[call-arg]
    assert s.effective_poll_interval() == 60
    s = Settings(
        poll_interval_seconds=99_999,
        minimum_check_interval=60,
        maximum_check_interval=600,
        _env_file=None,
    )  # type: ignore[call-arg]
    assert s.effective_poll_interval() == 600
    with pytest.raises(ValueError):
        Settings(minimum_check_interval=700, maximum_check_interval=600, _env_file=None)  # type: ignore[call-arg]


async def test_backoff_and_checkin_cadence() -> None:
    container = make_container(
        "checkin_open",
        poll_interval_seconds=300,
        minimum_check_interval=60,
        maximum_check_interval=1000,
    )
    mon = container.monitoring
    await mon.check_once()
    assert mon.next_interval() == 60  # check-in open -> tighter cadence
    mon.state.consecutive_errors = 5
    assert mon.next_interval() == 1000  # back-off capped


async def test_start_stop_loop() -> None:
    container = make_container()
    await container.monitoring.start_monitoring()
    assert container.monitoring.state.running
    await container.monitoring.stop_monitoring()
    assert container.monitoring.state.status is MonitoringStatus.STOPPED
