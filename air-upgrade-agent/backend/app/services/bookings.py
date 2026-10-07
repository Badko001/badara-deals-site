"""Several bookings, each watched for an upgrade on its own.

* Persisted: a label, the REDACTED reference (``PNR_****123``), the passenger
  count and (simulation) the mock scenario. Never the full reference.
* In memory only: the full reference, used to open the right booking on the
  airline site. After a restart the user types it again (real mode only).
* All bookings share one provider (one browser session); a lock makes sure
  only one booking is read or acted on at a time.
* Safety: if the page shows another booking than the one expected (redacted
  references differ), the snapshot is marked BOOKING_NOT_FOUND - data is never
  attributed to the wrong booking.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.orchestrator import LLMOrchestrator
from app.booking.providers.base import AirlineProvider
from app.booking.providers.mock_airfrance import MockAirFrance, MockAirFranceProvider
from app.browser.raw import RawPageObservation
from app.config import Settings
from app.models import BookingSnapshot, CostLimits, PageState, UpgradeOption
from app.models.actions import HumanConfirmation, ProviderActionResult, UpgradeExecutionResult
from app.monitoring.engine import MonitoringEngine
from app.notifications.service import NotificationService
from app.security.privacy import PrivacyManager, SensitiveKind, get_privacy_manager
from app.services.audit import AuditLog
from app.services.confirmations import DEFAULT_BOOKING_ID, ConfirmationService, booking_of
from app.services.db import BookingRow, Database
from app.services.executor import UpgradeExecutor
from app.services.runtime_settings import RuntimeSettings

_REFERENCE_RE = re.compile(r"^[A-Z0-9]{5,8}$")


class BookingInfo(BaseModel):
    booking_id: str
    label: str
    reference_redacted: str | None = None
    reference_in_memory: bool = False
    passengers_target: int = Field(ge=1, le=9)
    mock_scenario: str | None = None
    created_at: datetime | None = None


class BookingSummary(BaseModel):
    booking: BookingInfo
    status: str
    decision_status: str | None
    has_pending_confirmation: bool
    last_check: datetime | None


class BookingScopedProvider(AirlineProvider):
    """The shared provider, pointed at one booking for each operation."""

    def __init__(self, shared: AirlineProvider, manager: BookingManager, booking_id: str) -> None:
        super().__init__(shared.observation)
        self.shared = shared
        self.manager = manager
        self.booking_id = booking_id
        self.name = shared.name
        self.source = shared.source

    @property
    def enforce_rate_limit(self) -> bool:  # type: ignore[override]  # follows the shared provider
        return self.shared.enforce_rate_limit

    @property
    def session_ready(self) -> bool:
        return self.shared.session_ready

    async def _select(self) -> None:
        await self.shared.select_booking(self.booking_id, self.manager.reference(self.booking_id))

    async def read_raw(self) -> RawPageObservation:
        async with self.manager.lock:
            await self._select()
            return await self.shared.read_raw()

    def is_confirmed_by_airline(self) -> bool:
        return self.shared.is_confirmed_by_airline()

    async def take_snapshot(self) -> BookingSnapshot:
        async with self.manager.lock:
            await self._select()
            snapshot = await self.shared.take_snapshot()
        expected = self.manager.get(self.booking_id).reference_redacted
        shown = snapshot.anonymized_booking_id
        if expected and shown and expected != shown:
            # Another booking is displayed: never attribute its data to this one.
            return snapshot.model_copy(
                update={
                    "page_state": PageState.BOOKING_NOT_FOUND,
                    "confirmed_by_airline": False,
                    "upgrade_options": [],
                    "observed_messages": [
                        f"Réservation affichée {shown} différente de {expected}",
                        *snapshot.observed_messages,
                    ],
                }
            )
        return snapshot

    async def request_upgrade(
        self, option: UpgradeOption, confirmation: HumanConfirmation | None
    ) -> ProviderActionResult:
        async with self.manager.lock:
            await self._select()
            return await self.shared.request_upgrade(option, confirmation)

    async def _accept_official_offer(
        self, option: UpgradeOption, confirmation: HumanConfirmation
    ) -> ProviderActionResult:  # pragma: no cover - request_upgrade delegates
        raise NotImplementedError


@dataclass
class BookingContext:
    info: BookingInfo
    provider: BookingScopedProvider
    confirmations: ConfirmationService
    monitoring: MonitoringEngine
    executor: UpgradeExecutor
    last_execution: UpgradeExecutionResult | None = field(default=None)


class BookingManager:
    def __init__(
        self,
        *,
        shared_provider: AirlineProvider,
        db: Database,
        settings: Settings,
        runtime: RuntimeSettings,
        notifier: NotificationService,
        audit: AuditLog,
        orchestrator: LLMOrchestrator,
        privacy: PrivacyManager | None = None,
    ) -> None:
        self.shared = shared_provider
        self.db = db
        self.settings = settings
        self.runtime = runtime
        self.notifier = notifier
        self.audit = audit
        self.orchestrator = orchestrator
        self.privacy = privacy or get_privacy_manager()
        self.lock = asyncio.Lock()
        self._refs: dict[str, str] = {}  # full references: memory only
        self._contexts: dict[str, BookingContext] = {}
        self._load()

    # ------------------------------------------------------------ persistence
    def _load(self) -> None:
        with self.db.session() as session:
            rows = session.scalars(select(BookingRow).order_by(BookingRow.created_at)).all()
            infos = [self._info(r) for r in rows]
        if not infos:
            infos = [
                self._insert(
                    BookingInfo(
                        booking_id=DEFAULT_BOOKING_ID,
                        label="Ma réservation",
                        passengers_target=self.runtime.get_limits().passengers_target,
                    )
                )
            ]
        for info in infos:
            self._contexts[info.booking_id] = self._build(info)

    def _info(self, row: BookingRow) -> BookingInfo:
        return BookingInfo(
            booking_id=row.booking_id,
            label=row.label,
            reference_redacted=row.reference_redacted,
            reference_in_memory=row.booking_id in self._refs,
            passengers_target=row.passengers_target,
            mock_scenario=row.mock_scenario,
            created_at=row.created_at,
        )

    def _insert(self, info: BookingInfo) -> BookingInfo:
        with self.db.session() as session:
            session.add(
                BookingRow(
                    booking_id=info.booking_id,
                    label=info.label,
                    reference_redacted=info.reference_redacted,
                    passengers_target=info.passengers_target,
                    mock_scenario=info.mock_scenario,
                )
            )
            session.commit()
        return info

    def _save(self, info: BookingInfo) -> None:
        with self.db.session() as session:
            row = session.get(BookingRow, info.booking_id)
            if row is None:
                return
            row.label = info.label
            row.reference_redacted = info.reference_redacted
            row.passengers_target = info.passengers_target
            row.mock_scenario = info.mock_scenario
            session.commit()

    def _build(self, info: BookingInfo) -> BookingContext:
        provider = BookingScopedProvider(self.shared, self, info.booking_id)
        confirmations = ConfirmationService(
            self.db, self.settings.confirmation_ttl_seconds, booking_id=info.booking_id
        )
        if isinstance(self.shared, MockAirFranceProvider):
            mock = self.shared.mock_for(info.booking_id, self._refs.get(info.booking_id))
            if info.mock_scenario and info.mock_scenario != mock.scenario_name:
                mock.set_scenario(info.mock_scenario)
        monitoring = MonitoringEngine(
            provider=provider,
            orchestrator=self.orchestrator,
            limits=lambda: self.limits_for(info.booking_id),
            notifier=self.notifier,
            audit=self.audit,
            confirmations=confirmations,
            db=self.db,
            settings=self.settings,
            label=info.label,
        )
        executor = UpgradeExecutor(provider, confirmations, self.audit, self.settings)
        return BookingContext(info, provider, confirmations, monitoring, executor)

    # ------------------------------------------------------------ helpers
    def _clean_label(self, label: str) -> str:
        return self.privacy.sanitize_text(label.strip())[:80] or "Réservation"

    def _set_reference(self, booking_id: str, reference: str | None) -> str | None:
        if not reference:
            return None
        ref = reference.strip().upper()
        if not _REFERENCE_RE.fullmatch(ref):
            raise ValueError("Référence de réservation invalide (5 à 8 lettres/chiffres)")
        self._refs[booking_id] = ref
        self.privacy.register(ref, SensitiveKind.PNR)
        return self.privacy.redact_pnr(ref)

    def reference(self, booking_id: str) -> str | None:
        return self._refs.get(booking_id)

    def limits_for(self, booking_id: str) -> CostLimits:
        base = self.runtime.get_limits()
        return base.model_copy(update={"passengers_target": self.get(booking_id).passengers_target})

    # ------------------------------------------------------------ API
    def all(self) -> list[BookingContext]:
        return list(self._contexts.values())

    def first(self) -> BookingContext:
        return next(iter(self._contexts.values()))

    def context(self, booking_id: str | None) -> BookingContext:
        if booking_id is None:
            return self.first()
        try:
            return self._contexts[booking_id]
        except KeyError:
            raise KeyError(booking_id) from None

    def get(self, booking_id: str) -> BookingInfo:
        info = self.context(booking_id).info
        info.reference_in_memory = booking_id in self._refs
        return info

    def context_for_confirmation(self, confirmation_id: str) -> BookingContext | None:
        booking_id = booking_of(self.db, confirmation_id)
        return self._contexts.get(booking_id) if booking_id else None

    def add(
        self,
        label: str,
        reference: str | None,
        passengers_target: int,
        mock_scenario: str | None = None,
    ) -> BookingInfo:
        booking_id = uuid.uuid4().hex[:12]
        redacted = self._set_reference(booking_id, reference)
        info = self._insert(
            BookingInfo(
                booking_id=booking_id,
                label=self._clean_label(label),
                reference_redacted=redacted,
                reference_in_memory=redacted is not None,
                passengers_target=passengers_target,
                mock_scenario=mock_scenario
                if isinstance(self.shared, MockAirFranceProvider)
                else None,
            )
        )
        self._contexts[booking_id] = self._build(info)
        self.audit.record("BOOKING_ADDED", action=info.label, result=redacted or "sans référence")
        return info

    def update(
        self,
        booking_id: str,
        *,
        label: str | None = None,
        reference: str | None = None,
        passengers_target: int | None = None,
    ) -> BookingInfo:
        ctx = self.context(booking_id)
        info = ctx.info
        if label is not None:
            info.label = self._clean_label(label)
            ctx.monitoring.label = info.label
        if reference:
            info.reference_redacted = self._set_reference(booking_id, reference)
            if isinstance(self.shared, MockAirFranceProvider):
                mock = self.shared.mock_for(booking_id)
                mock.reference = self._refs[booking_id]
                mock.set_scenario(mock.scenario_name)
        if passengers_target is not None:
            info.passengers_target = passengers_target
        self._save(info)
        self.audit.record("BOOKING_UPDATED", action=info.label)
        return self.get(booking_id)

    def set_mock_scenario(self, booking_id: str, scenario: str) -> MockAirFrance:
        if not isinstance(self.shared, MockAirFranceProvider):
            raise LookupError("Mock provider not active")
        mock = self.shared.mock_for(booking_id, self._refs.get(booking_id))
        mock.set_scenario(scenario)  # KeyError if unknown
        info = self.context(booking_id).info
        info.mock_scenario = scenario
        self._save(info)
        return mock

    def mock(self, booking_id: str) -> MockAirFrance | None:
        if not isinstance(self.shared, MockAirFranceProvider):
            return None
        self.context(booking_id)
        return self.shared.mock_for(booking_id, self._refs.get(booking_id))

    async def delete(self, booking_id: str) -> None:
        if len(self._contexts) <= 1:
            raise ValueError("Impossible de supprimer la dernière réservation")
        ctx = self.context(booking_id)
        await ctx.monitoring.stop_monitoring()
        ctx.confirmations.expire_all()
        del self._contexts[booking_id]
        self._refs.pop(booking_id, None)
        with self.db.session() as session:
            row = session.get(BookingRow, booking_id)
            if row is not None:
                session.delete(row)
                session.commit()
        self.audit.record("BOOKING_DELETED", action=ctx.info.label)

    async def stop_all(self) -> None:
        for ctx in self.all():
            await ctx.monitoring.stop_monitoring()

    def summaries(self) -> list[BookingSummary]:
        return [
            BookingSummary(
                booking=self.get(ctx.info.booking_id),
                status=ctx.monitoring.state.status.value,
                decision_status=(
                    ctx.monitoring.last_decision.status.value
                    if ctx.monitoring.last_decision
                    else None
                ),
                has_pending_confirmation=ctx.confirmations.current_pending() is not None,
                last_check=ctx.monitoring.state.last_check,
            )
            for ctx in self.all()
        ]
