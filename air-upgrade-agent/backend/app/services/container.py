"""Wires every service together (one place, easy to override in tests)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agent.orchestrator import LLMClient, LLMOrchestrator
from app.booking.providers.airfrance import AirFranceProvider
from app.booking.providers.base import AirlineProvider
from app.booking.providers.mock_airfrance import MockAirFrance, MockAirFranceProvider
from app.config import ProviderName, Settings
from app.models.actions import UpgradeExecutionResult
from app.monitoring.engine import MonitoringEngine
from app.notifications.service import NotificationChannel, NotificationService, WebhookChannel
from app.services.audit import AuditLog
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
    confirmations: ConfirmationService
    runtime: RuntimeSettings
    provider: AirlineProvider
    orchestrator: LLMOrchestrator
    monitoring: MonitoringEngine
    executor: UpgradeExecutor
    mock: MockAirFrance | None = None
    last_execution: UpgradeExecutionResult | None = field(default=None)

    @classmethod
    def build(
        cls,
        settings: Settings,
        *,
        provider: AirlineProvider | None = None,
        llm_client: LLMClient | None = None,
        webhook_url: str | None = None,
    ) -> Container:
        db = Database(settings.database_url)
        audit = AuditLog(db)
        channels: list[NotificationChannel] = [WebhookChannel(webhook_url)] if webhook_url else []
        notifier = NotificationService(channels)
        confirmations = ConfirmationService(db, settings.confirmation_ttl_seconds)
        runtime = RuntimeSettings(db, settings)

        mock: MockAirFrance | None = None
        if provider is None:
            if settings.provider is ProviderName.AIR_FRANCE:
                provider = AirFranceProvider(settings)
            else:
                mock = MockAirFrance(settings.mock_scenario)
                provider = MockAirFranceProvider(mock)
        elif isinstance(provider, MockAirFranceProvider):
            mock = provider.mock

        orchestrator = (
            LLMOrchestrator(llm_client) if llm_client else LLMOrchestrator.from_settings(settings)
        )
        monitoring = MonitoringEngine(
            provider=provider,
            orchestrator=orchestrator,
            limits=runtime.get_limits,
            notifier=notifier,
            audit=audit,
            confirmations=confirmations,
            db=db,
            settings=settings,
        )
        executor = UpgradeExecutor(provider, confirmations, audit, settings)
        return cls(
            settings=settings,
            db=db,
            audit=audit,
            notifier=notifier,
            confirmations=confirmations,
            runtime=runtime,
            provider=provider,
            orchestrator=orchestrator,
            monitoring=monitoring,
            executor=executor,
            mock=mock,
        )
