"""Raw page observation: exactly the text the browser read, nothing interpreted.

This is the contract between the browser layer (or the mock airline) and the
:class:`~app.booking.observation.ObservationEngine`. Missing elements are ``None``.
It may contain personal data and therefore never leaves memory unredacted.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class PageKind(StrEnum):
    BOOKING = "booking"
    LOGIN = "login"
    CAPTCHA = "captcha"
    NOT_FOUND = "not_found"
    UNKNOWN = "unknown"


class RawPassengerRow(BaseModel):
    name_text: str | None = None  # personal: registered for redaction then discarded
    ticket_text: str | None = None  # personal: registered for redaction then discarded
    cabin_text: str | None = None
    seat_text: str | None = None
    eligibility_text: str | None = None


class RawUpgradeOffer(BaseModel):
    offer_id: str
    cabin_text: str | None = None
    price_text: str | None = None
    miles_text: str | None = None
    passengers_text: str | None = None
    availability_text: str | None = None
    has_accept_button: bool = False


class RawPageObservation(BaseModel):
    page_kind: PageKind = PageKind.UNKNOWN
    booking_reference_text: str | None = None  # personal
    flight_number_text: str | None = None
    origin_text: str | None = None
    destination_text: str | None = None
    departure_text: str | None = None
    aircraft_text: str | None = None
    passengers_count_text: str | None = None
    passenger_rows: list[RawPassengerRow] = Field(default_factory=list)
    cabin_text: str | None = None
    business_availability_text: str | None = None
    business_seats_text: str | None = None
    upgrade_offers: list[RawUpgradeOffer] = Field(default_factory=list)
    checkin_text: str | None = None
    messages: list[str] = Field(default_factory=list)
