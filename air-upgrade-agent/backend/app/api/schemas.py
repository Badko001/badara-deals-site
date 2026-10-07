"""API response / request schemas (anonymised by construction)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models import CostLimits, UpgradeDecision
from app.models.actions import UpgradeExecutionResult
from app.models.domain import Money
from app.monitoring.engine import ChangeEvent, MonitoringState
from app.notifications.service import Notification
from app.services.confirmations import PendingConfirmation


class RuntimeConfig(BaseModel):
    dry_run: bool
    debug_mode: bool
    provider: str
    llm_enabled: bool
    mock_scenario: str | None
    session_ready: bool


class PassengerView(BaseModel):
    anonymized_id: str
    current_cabin: str | None
    eligibility: str | None


class FlightView(BaseModel):
    anonymized_booking_id: str | None
    flight_number: str | None
    origin: str | None
    destination: str | None
    departure_datetime: datetime | None
    current_cabin: str | None
    target_cabin: str = "BUSINESS"
    passengers: list[PassengerView]
    business_available: bool | None
    business_seats_visible: int | None
    business_seats_provenance: str
    checkin_status: str | None
    observed_messages: list[str]
    confirmed_by_airline: bool
    snapshot_time: datetime


class DashboardResponse(BaseModel):
    config: RuntimeConfig
    limits: CostLimits
    monitoring: MonitoringState
    flight: FlightView | None
    decision: UpgradeDecision | None
    pending_confirmation: PendingConfirmation | None
    last_execution: UpgradeExecutionResult | None
    notifications: list[Notification]


class CheckResponse(BaseModel):
    decision: UpgradeDecision
    changes: list[ChangeEvent]
    notifications: list[Notification]


class LimitsUpdate(BaseModel):
    cash_limit: Money = Field(ge=0)
    miles_limit: int = Field(ge=0)
    passengers_target: int | None = Field(default=None, ge=1, le=9)


class SessionStart(BaseModel):
    booking_hint: str | None = Field(
        default=None,
        max_length=8,
        description="Optional booking reference to pick the right booking card. Kept in memory only.",
    )


class ScenarioUpdate(BaseModel):
    name: str
