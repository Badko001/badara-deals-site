"""Selectors of the MOCK AIR FRANCE HTML page (``app/browser/mock_page.py``). Verified by tests."""

from __future__ import annotations

from app.browser.raw import PageKind
from app.browser.selectors.base import SelectorMap, sel


def _t(name: str) -> str:
    return f'[data-testid="{name}"]'


MOCK_AIR_FRANCE_SELECTORS = SelectorMap(
    name="mock-airfrance",
    verified=True,
    official_hosts=("localhost", "127.0.0.1", ""),  # "" = file:// pages in tests
    page_markers={
        PageKind.CAPTCHA: sel(_t("captcha")),
        PageKind.LOGIN: sel(_t("login-form")),
        PageKind.NOT_FOUND: sel(_t("booking-not-found")),
        PageKind.BOOKING: sel(_t("booking-details")),
    },
    logged_in_marker=sel(_t("account-menu")),
    booking_link=sel(_t("booking-card")),
    fields={
        "booking_reference_text": sel(_t("booking-reference")),
        "flight_number_text": sel(_t("flight-number"), required=True),
        "origin_text": sel(_t("origin")),
        "destination_text": sel(_t("destination")),
        "departure_text": sel(_t("departure")),
        "aircraft_text": sel(_t("aircraft")),
        "passengers_count_text": sel(_t("passengers-count")),
        "cabin_text": sel(_t("booking-cabin")),
        "business_availability_text": sel(_t("business-availability")),
        "business_seats_text": sel(_t("business-seats")),
        "checkin_text": sel(_t("checkin-status")),
    },
    passenger_row=sel(_t("passenger-row")),
    passenger_fields={
        "name_text": sel(_t("passenger-name")),
        "ticket_text": sel(_t("passenger-ticket")),
        "cabin_text": sel(_t("passenger-cabin")),
        "seat_text": sel(_t("passenger-seat")),
        "eligibility_text": sel(_t("passenger-eligibility")),
    },
    offer_row=sel(_t("upgrade-offer")),
    offer_id_attribute="data-offer-id",
    offer_fields={
        "cabin_text": sel(_t("offer-cabin")),
        "price_text": sel(_t("offer-price")),
        "miles_text": sel(_t("offer-miles")),
        "passengers_text": sel(_t("offer-passengers")),
        "availability_text": sel(_t("offer-availability")),
    },
    offer_accept_button=sel(_t("offer-accept")),
    messages=sel(_t("page-message")),
    confirmation_total=sel(_t("confirm-total")),
    confirmation_miles=sel(_t("confirm-miles")),
    payment_form_marker=sel(_t("payment-form")),
    final_confirm_button=sel(_t("confirm-final")),
    pii_mask=(_t("booking-reference"), _t("passenger-name"), _t("passenger-ticket")),
)
