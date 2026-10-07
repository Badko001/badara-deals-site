"""Wires every service together (one place, easy to override in tests)."""

from __future__ import annotations

from dataclasses import dataclass

from app.agent.orchestrator import LLMClient, LLMOrchestrator
from app.booking.providers.airfrance import AirFranceProvider
from app.booking.providers.base import AirlineProvider
from app.booking.providers.mock_airfrance import MockAirFrance, MockAirFranceProvider
from app.config import FareProviderName, ProviderName, Settings
from app.models.actions import UpgradeExecutionResult
from app.monitoring.engine import MonitoringEngine
from app.notifications.service import NotificationChannel, NotificationService, WebhookChannel
from app.pricewatch.engine import PriceWatchEngine
from app.pricewatch.providers import DuffelFareProvider, FareProvider, MockFareProvider
from app.services.audit import AuditLog
from app.services.bookings import BookingManager
from app.services.confirmations import ConfirmationService
from app.services.db import Database
from app.services.executor import UpgradeExecutor
from app.services.runtime_settings import RuntimeSettings


@dataclass
class Container:
    settings: Settings
    db: Database
    audit: AuditLog
    notifier: NotificationService
    runtime: RuntimeSettings
    provider: AirlineProvider  # shared by all bookings (one browser session)
    orchestrator: LLMOrchestrator
    bookings: BookingManager
    pricewatch: PriceWatchEngine

    # Shortcuts to the first booking (single-booking usage, tests).
    @property
    def monitoring(self) -> MonitoringEngine:
        return self.bookings.first().monitoring

    @property
    def confirmations(self) -> ConfirmationService:
        return self.bookings.first().confirmations

    @property
    def executor(self) -> UpgradeExecutor:
        return self.bookings.first().executor

    @property
    def last_execution(self) -> UpgradeExecutionResult | None:
        return self.bookings.first().last_execution

    @property
    def mock(self) -> MockAirFrance | None:
        return self.bookings.mock(self.bookings.first().info.booking_id)

    @classmethod
    def build(
        cls,
        settings: Settings,
        *,
        provider: AirlineProvider | None = None,
        llm_client: LLMClient | None = None,
        webhook_url: str | None = None,
        fare_provider: FareProvider | None = None,
    ) -> Container:
        db = Database(settings.database_url)
        audit = AuditLog(db)
        channels: list[NotificationChannel] = [WebhookChannel(webhook_url)] if webhook_url else []
        notifier = NotificationService(channels)
        runtime = RuntimeSettings(db, settings)

        if provider is None:
            if settings.provider is ProviderName.AIR_FRANCE:
                provider = AirFranceProvider(settings)
            else:
                provider = MockAirFranceProvider(
                    MockAirFrance(settings.mock_scenario), default_scenario=settings.mock_scenario
                )

        orchestrator = (
            LLMOrchestrator(llm_client) if llm_client else LLMOrchestrator.from_settings(settings)
        )
        bookings = BookingManager(
            shared_provider=provider,
            db=db,
            settings=settings,
            runtime=runtime,
            notifier=notifier,
            audit=audit,
            orchestrator=orchestrator,
        )
        if fare_provider is None:
            if settings.fare_provider is FareProviderName.DUFFEL and settings.duffel_api_token:
                fare_provider = DuffelFareProvider(settings.duffel_api_token.get_secret_value())
            else:
                fare_provider = MockFareProvider()
        pricewatch = PriceWatchEngine(
            provider=fare_provider, db=db, notifier=notifier, audit=audit, settings=settings
        )
        return cls(
            settings=settings,
            db=db,
            audit=audit,
            notifier=notifier,
            runtime=runtime,
            provider=provider,
            orchestrator=orchestrator,
            bookings=bookings,
            pricewatch=pricewatch,
        )
