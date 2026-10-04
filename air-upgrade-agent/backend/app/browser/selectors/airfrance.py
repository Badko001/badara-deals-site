"""Air France selectors - SINGLE place where real-site selectors are defined.

STATUS: NOT VERIFIED (``verified=False``).

The real Air France DOM is not documented publicly and changes over time. The
candidates below are heuristics (text / role based) and MUST be validated during
a real session, logged in manually by the user, e.g. with::

    playwright codegen https://wwws.airfrance.fr

Procedure: docs/AIR_FRANCE_WORKFLOW.md. While ``verified`` is False:

* reading works best-effort: anything not found stays ``null`` (never guessed);
* the provider REFUSES to click anything (no real action), the user accepts
  any offer manually in the official interface.

Never add selectors targeting private APIs, hidden endpoints or anti-bot widgets.
"""

from __future__ import annotations

from app.browser.raw import PageKind
from app.browser.selectors.base import SelectorMap, sel

AIR_FRANCE_SELECTORS = SelectorMap(
    name="airfrance",
    verified=False,  # TODO(verify): set to True only after validation on a real session
    official_hosts=("airfrance.fr", "airfrance.com", "airfrance.sn", "airfrance.us"),
    page_markers={
        # A bot check is detected so that the USER solves it - never bypassed.
        PageKind.CAPTCHA: sel(
            "iframe[src*='captcha']",
            "iframe[title*='challenge' i]",
            "text=/vérifi\\w+ que vous n'êtes pas un robot/i",
        ),
        PageKind.LOGIN: sel(
            "form:has(input[type='password'])",
            "text=/se connecter|log in/i >> visible=true",
        ),
        PageKind.NOT_FOUND: sel("text=/réservation introuvable|booking not found/i"),
        PageKind.BOOKING: sel(
            "[data-testid*='booking-detail' i]",
            "main:has-text('Référence de réservation')",
            "main:has-text('Booking reference')",
        ),
    },
    logged_in_marker=sel(
        "[data-testid*='account' i]",
        "button:has-text('Mon compte')",
        "text=/se déconnecter|log out/i",
    ),
    booking_link=sel("a:has-text('Mes réservations')", "a:has-text('My bookings')"),
    fields={
        "booking_reference_text": sel(
            "[data-testid*='booking-reference' i]",
            "xpath=//*[contains(., 'Référence de réservation')]/following-sibling::*[1]",
        ),
        "flight_number_text": sel(
            "[data-testid*='flight-number' i]", "text=/\\bAF\\s?\\d{2,4}\\b/", required=True
        ),
        "origin_text": sel("[data-testid*='origin' i]"),
        "destination_text": sel("[data-testid*='destination' i]"),
        "departure_text": sel("[data-testid*='departure' i] time", "time[datetime]"),
        "aircraft_text": sel("[data-testid*='aircraft' i]"),
        "passengers_count_text": sel("[data-testid*='passenger-count' i]"),
        "cabin_text": sel("[data-testid*='cabin' i]", "text=/cabine|cabin/i"),
        "business_availability_text": sel("[data-testid*='business-availability' i]"),
        "business_seats_text": sel("[data-testid*='business-seats' i]"),
        "checkin_text": sel(
            "[data-testid*='check-in-status' i]", "text=/enregistrement|check-in/i"
        ),
    },
    passenger_row=sel("[data-testid*='passenger-item' i]", "li:has([data-testid*='passenger' i])"),
    passenger_fields={
        "name_text": sel("[data-testid*='passenger-name' i]"),
        "ticket_text": sel("[data-testid*='ticket-number' i]"),
        "cabin_text": sel("[data-testid*='cabin' i]"),
        "seat_text": sel("[data-testid*='seat' i]"),
        "eligibility_text": sel("[data-testid*='eligib' i]"),
    },
    offer_row=sel("[data-testid*='upgrade-offer' i]", "section:has-text('Surclassement')"),
    offer_id_attribute="data-offer-id",
    offer_fields={
        "cabin_text": sel("[data-testid*='cabin' i]", "text=/business/i"),
        "price_text": sel("[data-testid*='price' i]", "text=/€|gratuit|offert/i"),
        "miles_text": sel("[data-testid*='miles' i]", "text=/miles/i"),
        "passengers_text": sel("[data-testid*='passenger' i]", "text=/passager/i"),
        "availability_text": sel("[data-testid*='availability' i]"),
    },
    offer_accept_button=sel(
        "button:has-text('Surclasser')", "button:has-text('Upgrade')", "button:has-text('Accepter')"
    ),
    messages=sel("[role='alert']", "[data-testid*='message' i]"),
    confirmation_total=sel("[data-testid*='total' i]", "text=/total/i"),
    confirmation_miles=sel("[data-testid*='miles' i]"),
    payment_form_marker=sel(
        "input[autocomplete='cc-number']",
        "iframe[src*='payment' i]",
        "text=/paiement|payment|carte bancaire/i",
    ),
    final_confirm_button=sel("button:has-text('Confirmer')", "button:has-text('Confirm')"),
    pii_mask=(
        "[data-testid*='passenger-name' i]",
        "[data-testid*='booking-reference' i]",
        "[data-testid*='ticket' i]",
        "[data-testid*='email' i]",
        "[data-testid*='phone' i]",
    ),
)
