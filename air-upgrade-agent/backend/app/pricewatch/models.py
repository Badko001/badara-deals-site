"""Price watch models: what to watch, published fares observed, alerts.

Only fares published through an authorised source are used. Nothing here
books or pays: alerts link to the airline's official website.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.domain import Money, utcnow

_IATA = r"^[A-Z]{3}$"


class FareCabin(StrEnum):
    ECONOMY = "economy"
    PREMIUM_ECONOMY = "premium_economy"
    BUSINESS = "business"
    FIRST = "first"


class PriceWatch(BaseModel):
    """A route (or a set of destinations) to keep an eye on."""

    watch_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = Field(min_length=1, max_length=80)
    origin: str = Field(pattern=_IATA)
    destinations: list[str] = Field(min_length=1, max_length=12)
    depart_from: date
    depart_to: date
    trip_length_days: int | None = Field(
        default=None, ge=1, le=60, description="Round trip length; None = one way."
    )
    passengers: int = Field(default=1, ge=1, le=9)
    cabin: FareCabin = FareCabin.ECONOMY
    max_total_price: Money | None = Field(
        default=None, gt=0, description="Alert below this price, for all passengers."
    )
    airlines: list[str] = Field(
        default_factory=lambda: ["AF"], description="IATA codes; empty = all airlines."
    )
    active: bool = True

    @field_validator("origin", mode="before")
    @classmethod
    def _upper_origin(cls, v: object) -> object:
        return v.strip().upper() if isinstance(v, str) else v

    @field_validator("destinations", "airlines", mode="before")
    @classmethod
    def _upper_list(cls, v: object) -> object:
        if isinstance(v, list):
            return [x.strip().upper() for x in v if isinstance(x, str) and x.strip()]
        return v

    @field_validator("destinations")
    @classmethod
    def _iata_destinations(cls, v: list[str]) -> list[str]:
        for code in v:
            if len(code) != 3 or not code.isalpha():
                raise ValueError(f"Code aéroport invalide : {code}")
        return list(dict.fromkeys(v))

    @model_validator(mode="after")
    def _dates(self) -> Self:
        if self.depart_to < self.depart_from:
            raise ValueError("depart_to doit être après depart_from")
        if self.origin in self.destinations:
            raise ValueError("L'origine ne peut pas être une destination")
        return self

    @property
    def round_trip(self) -> bool:
        return self.trip_length_days is not None

    def sample_dates(self, max_dates: int, today: date | None = None) -> list[date]:
        """Up to ``max_dates`` departure dates spread evenly over the (future) window."""
        start = max(self.depart_from, (today or date.today()) + timedelta(days=1))
        if start > self.depart_to:
            return []
        span = (self.depart_to - start).days
        if span + 1 <= max_dates:
            return [start + timedelta(days=i) for i in range(span + 1)]
        step = span / (max_dates - 1) if max_dates > 1 else 0
        return list(
            dict.fromkeys(start + timedelta(days=round(i * step)) for i in range(max_dates))
        )


class FareQuote(BaseModel):
    """One published offer, as returned by the fare source."""

    destination: str
    depart_date: date
    return_date: date | None
    total_price: Money  # for all passengers
    currency: str
    carrier: str | None = None
    flight_numbers: list[str] = Field(default_factory=list)
    cabin: FareCabin
    passengers: int
    source: str
    observed_at: datetime = Field(default_factory=utcnow)

    @property
    def price_per_passenger(self) -> Decimal:
        return (self.total_price / self.passengers).quantize(Decimal("0.01"))


class AlertKind(StrEnum):
    BELOW_THRESHOLD = "BELOW_THRESHOLD"
    PRICE_DROP = "PRICE_DROP"
    NEW_LOW = "NEW_LOW"


class PriceAlert(BaseModel):
    watch_id: str
    watch_name: str
    kind: AlertKind
    quote: FareQuote
    previous_price: Money | None = None
    booking_url: str | None = None
    message: str
    timestamp: datetime = Field(default_factory=utcnow)


class WatchSummary(BaseModel):
    watch: PriceWatch
    best_current: FareQuote | None
    lowest_ever: FareQuote | None
    last_check: datetime | None
    quotes_count: int
