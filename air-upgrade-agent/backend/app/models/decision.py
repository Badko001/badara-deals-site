"""Structured decision output (strict schema - unknown fields are rejected)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.models.domain import Money, utcnow


class DecisionStatus(StrEnum):
    NO_OPPORTUNITY = "NO_OPPORTUNITY"
    OPPORTUNITY = "OPPORTUNITY"
    ACTION_REQUIRED = "ACTION_REQUIRED"


# Lower rank = more conservative. An LLM may only move a decision *down* this scale.
STATUS_RANK: dict[DecisionStatus, int] = {
    DecisionStatus.NO_OPPORTUNITY: 0,
    DecisionStatus.ACTION_REQUIRED: 1,
    DecisionStatus.OPPORTUNITY: 2,
}


class CostLimits(BaseModel):
    """User-adjustable limits. Defaults implement the strict FREE UPGRADE mode."""

    cash_limit: Money = Field(default=Decimal(0), ge=0)
    miles_limit: int = Field(default=0, ge=0)
    passengers_target: int = Field(default=3, ge=1, le=9)

    @property
    def free_upgrade_mode(self) -> bool:
        return self.cash_limit == 0 and self.miles_limit == 0


class RejectedOption(BaseModel):
    option_id: str
    reason: str
    cash_cost: Money | None = None
    miles_cost: int | None = None


class UpgradeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: DecisionStatus
    reason: str
    passengers_target: int
    passengers_eligible: int | None
    business_available: bool | None
    business_seats_required: int
    business_seats_observed: int | None
    cash_cost: Money | None
    miles_cost: int | None
    recommendation: str
    confidence: float = Field(ge=0.0, le=1.0)
    requires_human_confirmation: bool
    option_id: str | None = None
    rejected_options: list[RejectedOption] = Field(default_factory=list)
    data_issues: list[str] = Field(default_factory=list)
    snapshot_id: str | None = None
    decided_by: str = "DETERMINISTIC_ENGINE"
    evaluated_at: datetime = Field(default_factory=utcnow)


class LLMDecisionPayload(BaseModel):
    """Exact schema the LLM must return. Anything else is refused."""

    model_config = ConfigDict(extra="forbid")

    status: DecisionStatus
    reason: str = Field(min_length=1, max_length=1000)
    passengers_target: int
    passengers_eligible: int | None
    business_seats_observed: int | None
    cash_cost: float | None
    miles_cost: int | None
    recommendation: str = Field(min_length=1, max_length=1000)
    requires_human_confirmation: bool
