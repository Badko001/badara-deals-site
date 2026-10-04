"""Human-in-the-loop action models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.models.domain import Money, utcnow


class HumanConfirmation(BaseModel):
    """Proof that the user explicitly clicked CONFIRM for *this* offer.

    Only :class:`~app.services.confirmations.ConfirmationService` creates it.
    A provider refuses any real action without it.
    """

    model_config = ConfigDict(frozen=True)

    confirmation_id: str
    option_id: str
    snapshot_id: str
    max_cash: Money
    max_miles: int
    passengers: int
    confirmed_at: datetime
    expires_at: datetime

    def is_valid(self, now: datetime | None = None) -> bool:
        return (now or utcnow()) < self.expires_at


class ExecutionStatus(StrEnum):
    DRY_RUN_SIMULATED = "DRY_RUN_SIMULATED"
    CONFIRMED_BY_AIRLINE = "CONFIRMED_BY_AIRLINE"
    NOT_CONFIRMED_BY_AIRLINE = "NOT_CONFIRMED_BY_AIRLINE"
    ABORTED = "ABORTED"


class UpgradeExecutionResult(BaseModel):
    status: ExecutionStatus
    message: str
    option_id: str | None = None
    verification_snapshot_id: str | None = None
    timestamp: datetime = Field(default_factory=utcnow)


class ProviderActionResult(BaseModel):
    """What the provider did in the official UI (before independent verification)."""

    submitted: bool
    message: str
