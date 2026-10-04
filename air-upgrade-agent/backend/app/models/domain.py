"""Core domain models.

Every value that comes from the airline UI is wrapped in :class:`Observed`, which
records its provenance:

* ``OBSERVED``  - read verbatim on the official airline page;
* ``INFERRED``  - derived by reasoning (never used as proof of availability);
* ``UNKNOWN``   - not visible. The value is then ``None`` - never an estimate.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Generic, Self, TypeVar

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, model_validator

T = TypeVar("T")

# Decimals are serialised as JSON numbers (not strings) for the frontend / LLM.
Money = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


def utcnow() -> datetime:
    return datetime.now(UTC)


class Provenance(StrEnum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"


class Cabin(StrEnum):
    ECONOMY = "ECONOMY"
    PREMIUM_ECONOMY = "PREMIUM_ECONOMY"
    BUSINESS = "BUSINESS"
    FIRST = "FIRST"


class Eligibility(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"


class CheckinStatus(StrEnum):
    NOT_OPEN = "NOT_OPEN"
    OPEN = "OPEN"
    CHECKED_IN = "CHECKED_IN"
    CLOSED = "CLOSED"


class PageState(StrEnum):
    BOOKING_VISIBLE = "BOOKING_VISIBLE"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    HUMAN_VERIFICATION_REQUIRED = "HUMAN_VERIFICATION_REQUIRED"  # CAPTCHA: user solves it
    BOOKING_NOT_FOUND = "BOOKING_NOT_FOUND"
    UNEXPECTED = "UNEXPECTED"


class SnapshotSource(StrEnum):
    AIR_FRANCE_WEB = "AIR_FRANCE_WEB"  # official UI, read by the browser agent
    MOCK_AIR_FRANCE = "MOCK_AIR_FRANCE"  # simulated airline UI (tests / DRY_RUN)
    MANUAL_ENTRY = "MANUAL_ENTRY"  # typed by a human: never airline-confirmed
    LLM_INFERENCE = "LLM_INFERENCE"  # never airline-confirmed


class PaymentType(StrEnum):
    FREE = "FREE"
    CASH = "CASH"
    MILES = "MILES"
    MILES_CASH = "MILES_CASH"
    UNKNOWN = "UNKNOWN"


class Observed(BaseModel, Generic[T]):
    """A value together with where it comes from."""

    model_config = ConfigDict(frozen=True)

    value: T | None = None
    provenance: Provenance = Provenance.UNKNOWN
    evidence: str | None = Field(
        default=None, description="Short, non-personal description of what was seen."
    )

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.provenance is Provenance.UNKNOWN and self.value is not None:
            raise ValueError("UNKNOWN values must be null")
        if self.provenance is not Provenance.UNKNOWN and self.value is None:
            raise ValueError("A null value must have UNKNOWN provenance")
        return self

    @property
    def is_observed(self) -> bool:
        return self.provenance is Provenance.OBSERVED

    @property
    def observed_value(self) -> T | None:
        """The value only if it was actually observed - inferences are dropped."""
        return self.value if self.is_observed else None

    @classmethod
    def seen(cls, value: T, evidence: str | None = None) -> Observed[T]:
        return cls(value=value, provenance=Provenance.OBSERVED, evidence=evidence)

    @classmethod
    def inferred(cls, value: T, evidence: str | None = None) -> Observed[T]:
        return cls(value=value, provenance=Provenance.INFERRED, evidence=evidence)

    @classmethod
    def unknown(cls) -> Observed[T]:
        return cls()


class Passenger(BaseModel):
    """A passenger, identified only by internal / anonymised identifiers."""

    internal_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    anonymized_id: str = Field(pattern=r"^PASSENGER_\d{3}$")
    current_cabin: Observed[Cabin] = Field(default_factory=Observed[Cabin])
    current_seat: Observed[str] = Field(default_factory=Observed[str])
    eligibility_status: Observed[Eligibility] = Field(default_factory=Observed[Eligibility])


class Flight(BaseModel):
    airline: str
    flight_number: str
    origin: str | None = None
    destination: str | None = None
    departure_datetime: datetime | None = None
    aircraft: str | None = None


class Booking(BaseModel):
    anonymized_booking_id: str
    flight: Flight
    passengers: list[Passenger]
    current_cabin: Observed[Cabin] = Field(default_factory=Observed[Cabin])
    checkin_status: Observed[CheckinStatus] = Field(default_factory=Observed[CheckinStatus])


class UpgradeOption(BaseModel):
    """An upgrade offer as displayed by the airline. Unknown prices stay ``None``."""

    option_id: str
    cabin: Cabin
    cash_price: Money | None = None
    currency: str | None = None
    miles_price: int | None = None
    miles_cash_price: Money | None = None  # cash component of a Miles + Cash offer
    passengers_covered: int | None = Field(
        default=None, description="How many passengers the single offer applies to."
    )
    availability: bool | None = None
    actionable: bool = Field(
        default=False, description="An official accept button is displayed for this offer."
    )
    provenance: Provenance = Provenance.OBSERVED
    source: SnapshotSource
    label: str | None = None
    timestamp: datetime = Field(default_factory=utcnow)

    @property
    def payment_type(self) -> PaymentType:
        cash = self.cash_price
        miles = self.miles_price
        mixed = self.miles_cash_price
        if cash is None and miles is None and mixed is None:
            return PaymentType.UNKNOWN
        if miles and (mixed or cash):
            return PaymentType.MILES_CASH
        if miles:
            return PaymentType.MILES
        if (cash or Decimal(0)) > 0 or (mixed or Decimal(0)) > 0:
            return PaymentType.CASH
        # All known components are zero. Both cash and miles must be known to be "free".
        if cash is not None and miles is not None:
            return PaymentType.FREE
        return PaymentType.UNKNOWN

    @property
    def total_cash(self) -> Decimal | None:
        if self.cash_price is None and self.miles_cash_price is None:
            return None
        return (self.cash_price or Decimal(0)) + (self.miles_cash_price or Decimal(0))


class BookingSnapshot(BaseModel):
    """What the browser actually saw at a given time. Immutable once built."""

    model_config = ConfigDict(frozen=True)

    snapshot_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: datetime = Field(default_factory=utcnow)
    page_state: PageState = PageState.BOOKING_VISIBLE
    anonymized_booking_id: str | None = None
    flight: Flight | None = None
    passengers_count: Observed[int] = Field(default_factory=Observed[int])
    passengers: list[Passenger] = Field(default_factory=list)
    current_cabin: Observed[Cabin] = Field(default_factory=Observed[Cabin])
    business_available: Observed[bool] = Field(default_factory=Observed[bool])
    business_seats_visible: Observed[int] = Field(default_factory=Observed[int])
    upgrade_options: list[UpgradeOption] = Field(default_factory=list)
    checkin_status: Observed[CheckinStatus] = Field(default_factory=Observed[CheckinStatus])
    observed_messages: list[str] = Field(default_factory=list)
    source: SnapshotSource
    confirmed_by_airline: bool = Field(
        default=False,
        description="True only when the data was read on the airline's own system.",
    )
