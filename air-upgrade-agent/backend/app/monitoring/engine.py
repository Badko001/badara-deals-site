"""MonitoringEngine - periodic, polite re-reading of the booking.

* Never faster than ``MINIMUM_CHECK_INTERVAL`` on a real airline site.
* Tighter cadence (minimum interval) once check-in is open, exponential back-off
  on errors (capped at ``MAXIMUM_CHECK_INTERVAL``), stop after repeated errors.
* Login / CAPTCHA pages pause the work and ask the user: nothing is bypassed.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, Field

from app.agent.orchestrator import LLMOrchestrator
from app.booking.providers.base import AirlineProvider
from app.config import Settings
from app.errors import AirUpgradeError
from app.models import (
    BookingSnapshot,
    CheckinStatus,
    CostLimits,
    DecisionStatus,
    UpgradeDecision,
)
from app.models.domain import utcnow
from app.notifications.service import (
    Notification,
    NotificationEvent,
    NotificationService,
    build_message,
)
from app.security.privacy import redact_sensitive_data
from app.services.audit import AuditLog
from app.services.confirmations import ConfirmationService
from app.services.db import Database, SnapshotRow

logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_ERRORS = 3


class RateLimited(AirUpgradeError):
    critical = False


class ChangeType(StrEnum):
    BUSINESS_BECAME_AVAILABLE = "BUSINESS_BECAME_AVAILABLE"
    BUSINESS_NO_LONGER_AVAILABLE = "BUSINESS_NO_LONGER_AVAILABLE"
    SEATS_CHANGED = "SEATS_CHANGED"
    NEW_UPGRADE_OPTION = "NEW_UPGRADE_OPTION"
    UPGRADE_OPTION_REMOVED = "UPGRADE_OPTION_REMOVED"
    PRICE_CHANGED = "PRICE_CHANGED"
    CHECKIN_OPENED = "CHECKIN_OPENED"
    CHECKIN_STATUS_CHANGED = "CHECKIN_STATUS_CHANGED"
    CABIN_CHANGED = "CABIN_CHANGED"
    PAGE_STATE_CHANGED = "PAGE_STATE_CHANGED"


class ChangeEvent(BaseModel):
    type: ChangeType
    detail: str


class MonitoringStatus(StrEnum):
    IDLE = "IDLE"
    MONITORING = "MONITORING"
    OPPORTUNITY_FOUND = "OPPORTUNITY_FOUND"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class MonitoringState(BaseModel):
    status: MonitoringStatus = MonitoringStatus.IDLE
    running: bool = False
    last_check: datetime | None = None
    next_check: datetime | None = None
    interval_seconds: int = 0
    checks_count: int = 0
    consecutive_errors: int = 0
    last_error: str | None = None


class CheckResult(BaseModel):
    snapshot: BookingSnapshot
    decision: UpgradeDecision
    changes: list[ChangeEvent] = Field(default_factory=list)
    notifications: list[Notification] = Field(default_factory=list)


def compare_snapshots(prev: BookingSnapshot | None, curr: BookingSnapshot) -> list[ChangeEvent]:
    """Differences between two snapshots, based on observed values only."""
    if prev is None:
        return []
    changes: list[ChangeEvent] = []
    if prev.page_state is not curr.page_state:
        changes.append(
            ChangeEvent(
                type=ChangeType.PAGE_STATE_CHANGED, detail=f"{prev.page_state} -> {curr.page_state}"
            )
        )

    a, b = prev.business_available.observed_value, curr.business_available.observed_value
    if a is not True and b is True:
        changes.append(
            ChangeEvent(type=ChangeType.BUSINESS_BECAME_AVAILABLE, detail="Business disponible")
        )
    elif a is True and b is False:
        changes.append(
            ChangeEvent(
                type=ChangeType.BUSINESS_NO_LONGER_AVAILABLE, detail="Business indisponible"
            )
        )

    s1, s2 = prev.business_seats_visible.observed_value, curr.business_seats_visible.observed_value
    if s1 != s2:
        changes.append(ChangeEvent(type=ChangeType.SEATS_CHANGED, detail=f"{s1} -> {s2}"))

    before = {o.option_id: o for o in prev.upgrade_options}
    after = {o.option_id: o for o in curr.upgrade_options}
    for oid in after.keys() - before.keys():
        changes.append(ChangeEvent(type=ChangeType.NEW_UPGRADE_OPTION, detail=oid))
    for oid in before.keys() - after.keys():
        changes.append(ChangeEvent(type=ChangeType.UPGRADE_OPTION_REMOVED, detail=oid))
    for oid in before.keys() & after.keys():
        o1, o2 = before[oid], after[oid]
        if (o1.total_cash, o1.miles_price) != (o2.total_cash, o2.miles_price):
            changes.append(
                ChangeEvent(
                    type=ChangeType.PRICE_CHANGED,
                    detail=f"{oid}: {o1.total_cash}€/{o1.miles_price}mi -> {o2.total_cash}€/{o2.miles_price}mi",
                )
            )

    c1, c2 = prev.checkin_status.observed_value, curr.checkin_status.observed_value
    if c1 != c2:
        kind = (
            ChangeType.CHECKIN_OPENED
            if c2 is CheckinStatus.OPEN
            else ChangeType.CHECKIN_STATUS_CHANGED
        )
        changes.append(ChangeEvent(type=kind, detail=f"{c1} -> {c2}"))

    cab1, cab2 = prev.current_cabin.observed_value, curr.current_cabin.observed_value
    if cab1 != cab2:
        changes.append(ChangeEvent(type=ChangeType.CABIN_CHANGED, detail=f"{cab1} -> {cab2}"))
    return changes


def detect_change(prev: BookingSnapshot | None, curr: BookingSnapshot) -> bool:
    return bool(compare_snapshots(prev, curr))


class MonitoringEngine:
    def __init__(
        self,
        *,
        provider: AirlineProvider,
        orchestrator: LLMOrchestrator,
        limits: Callable[[], CostLimits],
        notifier: NotificationService,
        audit: AuditLog,
        confirmations: ConfirmationService,
        db: Database,
        settings: Settings,
        label: str | None = None,
    ) -> None:
        self.provider = provider
        self.orchestrator = orchestrator
        self.limits = limits
        self.notifier = notifier
        self.audit = audit
        self.confirmations = confirmations
        self.db = db
        self.settings = settings
        self.label = label  # booking name, shown in alerts when several bookings exist
        self.state = MonitoringState(interval_seconds=settings.effective_poll_interval())
        self.last_snapshot: BookingSnapshot | None = None
        self.last_decision: UpgradeDecision | None = None
        self._last_request: float | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()

    # ----------------------------------------------------------- primitives
    async def take_snapshot(self) -> BookingSnapshot:
        if self.provider.enforce_rate_limit and self._last_request is not None:
            elapsed = time.monotonic() - self._last_request
            if elapsed < self.settings.minimum_check_interval:
                raise RateLimited(
                    f"Minimum interval not reached ({int(self.settings.minimum_check_interval - elapsed)}s left)"
                )
        self._last_request = time.monotonic()
        return await self.provider.take_snapshot()

    async def detect_opportunity(self, snapshot: BookingSnapshot) -> UpgradeDecision:
        return await self.orchestrator.decide(snapshot, self.limits())

    compare_snapshots = staticmethod(compare_snapshots)
    detect_change = staticmethod(detect_change)

    def next_interval(self) -> int:
        s = self.settings
        base = s.effective_poll_interval()
        if (
            self.last_snapshot is not None
            and self.last_snapshot.checkin_status.observed_value is CheckinStatus.OPEN
        ):
            base = s.minimum_check_interval
        if self.state.consecutive_errors:
            base = base * 2**self.state.consecutive_errors
        return max(s.minimum_check_interval, min(base, s.maximum_check_interval))

    # ----------------------------------------------------------- one check
    async def check_once(self) -> CheckResult:
        async with self._lock:
            snapshot = await self.take_snapshot()
            decision = await self.detect_opportunity(snapshot)
            prev_snapshot, prev_decision = self.last_snapshot, self.last_decision
            changes = compare_snapshots(prev_snapshot, snapshot)
            notifications = await self._handle_transitions(
                prev_decision, decision, changes, snapshot
            )

            self.last_snapshot, self.last_decision = snapshot, decision
            self._persist(snapshot, decision)
            self.audit.record(
                "CHECK",
                decision=decision.status.value,
                action="read official booking page",
                result=decision.reason[:500],
                details={
                    "changes": [c.model_dump() for c in changes],
                    "confidence": decision.confidence,
                    "decided_by": decision.decided_by,
                },
            )
            self.state.last_check = utcnow()
            self.state.checks_count += 1
            self.state.consecutive_errors = 0
            self.state.last_error = None
            self.state.status = {
                DecisionStatus.OPPORTUNITY: MonitoringStatus.OPPORTUNITY_FOUND,
                DecisionStatus.ACTION_REQUIRED: MonitoringStatus.ACTION_REQUIRED,
            }.get(
                decision.status,
                MonitoringStatus.MONITORING if self.state.running else MonitoringStatus.IDLE,
            )
            return CheckResult(
                snapshot=snapshot, decision=decision, changes=changes, notifications=notifications
            )

    async def _handle_transitions(
        self,
        prev: UpgradeDecision | None,
        curr: UpgradeDecision,
        changes: list[ChangeEvent],
        snapshot: BookingSnapshot,
    ) -> list[Notification]:
        sent: list[Notification] = []
        was_opp = prev is not None and prev.status is DecisionStatus.OPPORTUNITY
        is_opp = curr.status is DecisionStatus.OPPORTUNITY

        if is_opp and not was_opp:
            self.confirmations.create_pending(curr, snapshot)
            sent.append(await self._notify(NotificationEvent.OPPORTUNITY_FOUND, curr))
        elif (
            is_opp
            and was_opp
            and prev is not None
            and (
                (prev.option_id, prev.cash_cost, prev.miles_cost)
                != (curr.option_id, curr.cash_cost, curr.miles_cost)
            )
        ):
            self.confirmations.create_pending(curr, snapshot)
            sent.append(await self._notify(NotificationEvent.OPPORTUNITY_CHANGED, curr))
        elif was_opp and not is_opp:
            self.confirmations.expire_all()
            sent.append(await self._notify(NotificationEvent.NO_LONGER_AVAILABLE, curr))

        if any(c.type is ChangeType.CHECKIN_OPENED for c in changes):
            sent.append(await self._notify(NotificationEvent.CHECKIN_OPEN, curr))
        if curr.status is DecisionStatus.ACTION_REQUIRED and (
            prev is None or prev.status is not DecisionStatus.ACTION_REQUIRED
        ):
            sent.append(await self._notify(NotificationEvent.ACTION_REQUIRED, curr))
        return sent

    async def _notify(
        self, event: NotificationEvent, decision: UpgradeDecision | None = None
    ) -> Notification:
        text = build_message(event, decision)
        if self.label:
            text = f"[{self.label}] {text}"
        return await self.notifier.notify(event, decision, message=text)

    def _persist(self, snapshot: BookingSnapshot, decision: UpgradeDecision) -> None:
        with self.db.session() as session:
            session.add(
                SnapshotRow(
                    snapshot_id=snapshot.snapshot_id,
                    timestamp=snapshot.timestamp,
                    data=redact_sensitive_data(snapshot),
                    decision=redact_sensitive_data(decision),
                )
            )
            session.commit()

    # ----------------------------------------------------------- loop
    async def start_monitoring(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self.state.running = True
        self.state.status = MonitoringStatus.MONITORING
        self.audit.record("MONITORING_STARTED", action="start")
        self._task = asyncio.create_task(self._run())

    async def stop_monitoring(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        self.state.running = False
        self.state.next_check = None
        self.state.status = MonitoringStatus.STOPPED
        self.audit.record("MONITORING_STOPPED", action="stop")

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.check_once()
            except RateLimited:
                pass
            except Exception as exc:  # never guess after an error
                self.state.consecutive_errors += 1
                self.state.last_error = type(exc).__name__
                self.audit.record("CHECK_ERROR", result=type(exc).__name__)
                if self.state.consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    self.state.status = MonitoringStatus.ERROR
                    self.state.running = False
                    await self._notify(NotificationEvent.ACTION_REQUIRED)
                    return
            interval = self.next_interval()
            self.state.interval_seconds = interval
            self.state.next_check = utcnow() + timedelta(seconds=interval)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
