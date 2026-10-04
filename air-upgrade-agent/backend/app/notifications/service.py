"""NotificationService - short, anonymised alerts."""

from __future__ import annotations

import logging
import uuid
from collections import deque
from datetime import datetime
from enum import StrEnum
from typing import Protocol

import httpx
from pydantic import BaseModel, Field

from app.models import UpgradeDecision
from app.models.domain import utcnow
from app.security.privacy import get_privacy_manager

logger = logging.getLogger(__name__)


class NotificationEvent(StrEnum):
    OPPORTUNITY_FOUND = "OPPORTUNITY_FOUND"
    OPPORTUNITY_CHANGED = "OPPORTUNITY_CHANGED"
    CHECKIN_OPEN = "CHECKIN_OPEN"
    NO_LONGER_AVAILABLE = "NO_LONGER_AVAILABLE"
    ACTION_REQUIRED = "ACTION_REQUIRED"


class Notification(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    event: NotificationEvent
    message: str
    timestamp: datetime = Field(default_factory=utcnow)


class NotificationChannel(Protocol):
    async def send(self, notification: Notification) -> None: ...


class LogChannel:
    async def send(self, notification: Notification) -> None:
        logger.info("[%s] %s", notification.event.value, notification.message)


class InMemoryChannel:
    """Feeds the dashboard."""

    def __init__(self, maxlen: int = 100) -> None:
        self.items: deque[Notification] = deque(maxlen=maxlen)

    async def send(self, notification: Notification) -> None:
        self.items.appendleft(notification)


class WebhookChannel:
    """Optional: Teams / Slack-compatible incoming webhook ({"text": ...})."""

    def __init__(self, url: str, timeout: float = 5.0) -> None:
        self.url = url
        self.timeout = timeout

    async def send(self, notification: Notification) -> None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                await client.post(self.url, json={"text": notification.message})
        except httpx.HTTPError:
            logger.warning("Webhook notification failed")


def _cost(decision: UpgradeDecision) -> str:
    cash = "?" if decision.cash_cost is None else f"{decision.cash_cost:g}"
    miles = "?" if decision.miles_cost is None else str(decision.miles_cost)
    return f"Coût : {cash} € / {miles} Miles."


def build_message(event: NotificationEvent, decision: UpgradeDecision | None = None) -> str:
    n = decision.passengers_target if decision else 3
    match event:
        case NotificationEvent.OPPORTUNITY_FOUND:
            assert decision is not None
            return f"Opportunité Business détectée pour {n} passagers.\n{_cost(decision)}\nConfirmation requise."
        case NotificationEvent.OPPORTUNITY_CHANGED:
            assert decision is not None
            return f"Opportunité Business modifiée ({n} passagers).\n{_cost(decision)}\nVérifiez avant de confirmer."
        case NotificationEvent.NO_LONGER_AVAILABLE:
            return "L'opportunité Business n'est plus proposée. Surveillance en cours."
        case NotificationEvent.CHECKIN_OPEN:
            return "L'enregistrement est ouvert. Surveillance renforcée des offres."
        case NotificationEvent.ACTION_REQUIRED:
            hint = decision.recommendation if decision else "Votre intervention est requise."
            return f"Action requise : {hint}"
    raise ValueError(event)  # pragma: no cover


class NotificationService:
    def __init__(self, channels: list[NotificationChannel] | None = None) -> None:
        self.memory = InMemoryChannel()
        self.channels: list[NotificationChannel] = [self.memory, LogChannel(), *(channels or [])]

    async def notify(
        self, event: NotificationEvent, decision: UpgradeDecision | None = None
    ) -> Notification:
        message = get_privacy_manager().sanitize_text(build_message(event, decision))
        notification = Notification(event=event, message=message)
        for channel in self.channels:
            await channel.send(notification)
        return notification

    def recent(self, limit: int = 20) -> list[Notification]:
        return list(self.memory.items)[:limit]
