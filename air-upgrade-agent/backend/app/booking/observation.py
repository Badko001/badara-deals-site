"""ObservationEngine: turns what the browser *actually saw* into structured data.

Golden rule: never invent. A text that is missing or cannot be parsed
unambiguously produces ``null`` with provenance ``UNKNOWN``.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.browser.raw import PageKind, RawPageObservation, RawUpgradeOffer
from app.models import (
    BookingSnapshot,
    Cabin,
    CheckinStatus,
    Eligibility,
    Flight,
    Observed,
    PageState,
    Passenger,
    SnapshotSource,
    UpgradeOption,
)
from app.security.privacy import PrivacyManager, SensitiveKind, get_privacy_manager

_PAGE_STATES = {
    PageKind.BOOKING: PageState.BOOKING_VISIBLE,
    PageKind.LOGIN: PageState.AUTHENTICATION_REQUIRED,
    PageKind.CAPTCHA: PageState.HUMAN_VERIFICATION_REQUIRED,
    PageKind.NOT_FOUND: PageState.BOOKING_NOT_FOUND,
    PageKind.UNKNOWN: PageState.UNEXPECTED,
}

_FREE_WORDS = re.compile(r"(?i)\b(gratuit|gratuite|offert|offerte|free|sans frais|complimentary)\b")
_INT_RE = re.compile(r"\d[\d\s .,]*")


def _norm(text: str | None) -> str:
    return " ".join((text or "").lower().split())


def parse_cabin(text: str | None) -> Cabin | None:
    t = _norm(text)
    if not t:
        return None
    if "premium" in t:
        return Cabin.PREMIUM_ECONOMY
    if "business" in t or "affaires" in t:
        return Cabin.BUSINESS
    if "première" in t or "premiere" in t or "first" in t:
        return Cabin.FIRST
    if "economy" in t or "économi" in t or "economi" in t or t == "eco":
        return Cabin.ECONOMY
    return None


def parse_availability(text: str | None) -> bool | None:
    t = _norm(text)
    if not t:
        return None
    negatives = (
        "indisponible",
        "unavailable",
        "not available",
        "non disponible",
        "complet",
        "sold out",
        "épuisé",
        "plus disponible",
        "no longer available",
    )
    if any(n in t for n in negatives):
        return False
    if "disponible" in t or "available" in t:
        return True
    return None


def parse_int(text: str | None) -> int | None:
    """First integer in the text; ``"aucun"/"none"`` -> 0; ambiguous -> None."""
    t = _norm(text)
    if not t:
        return None
    if re.search(r"\b(aucun|aucune|none|no seats?|zéro|zero)\b", t):
        return 0
    match = _INT_RE.search(t)
    if not match:
        return None
    digits = re.sub(r"[\s .,]", "", match.group(0))
    return int(digits) if digits.isdigit() else None


def parse_money(text: str | None) -> Decimal | None:
    """Parse a euro amount ("250 €", "1 250,50 €", "EUR 90"). Free labels -> 0."""
    t = _norm(text)
    if not t:
        return None
    match = re.search(r"(\d[\d\s .]*(?:,\d{1,2})?|\d+(?:\.\d{1,2})?)\s*(?:€|eur)", t)
    if not match:
        match = re.search(r"(?:€|eur)\s*(\d[\d\s .]*(?:,\d{1,2})?)", t)
    if match:
        raw = re.sub(r"[\s ]", "", match.group(1))
        if "," in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"\d{1,3}(\.\d{3})+", raw):
            raw = raw.replace(".", "")
        try:
            return Decimal(raw)
        except InvalidOperation:
            return None
    if _FREE_WORDS.search(t):
        return Decimal(0)
    return None


def parse_miles(text: str | None) -> int | None:
    t = _norm(text)
    if not t:
        return None
    match = re.search(r"(\d[\d\s .,]*)\s*miles", t)
    if match:
        digits = re.sub(r"[\s .,]", "", match.group(1))
        return int(digits) if digits.isdigit() else None
    return None


def parse_checkin(text: str | None) -> CheckinStatus | None:
    t = _norm(text)
    if not t:
        return None
    if any(
        k in t for k in ("pas encore ouvert", "not yet open", "ouvrira", "opens on", "opens at")
    ):
        return CheckinStatus.NOT_OPEN
    if any(k in t for k in ("fermé", "ferme", "closed")):
        return CheckinStatus.CLOSED
    if any(k in t for k in ("vous êtes enregistré", "checked in", "enregistrement effectué")):
        return CheckinStatus.CHECKED_IN
    if any(k in t for k in ("ouvert", "open", "enregistrez-vous", "check in now")):
        return CheckinStatus.OPEN
    return None


def parse_eligibility(text: str | None) -> Eligibility | None:
    t = _norm(text)
    if not t:
        return None
    if any(
        k in t for k in ("non éligible", "not eligible", "inéligible", "ineligible", "non eligible")
    ):
        return Eligibility.NOT_ELIGIBLE
    if "éligible" in t or "eligible" in t:
        return Eligibility.ELIGIBLE
    return None


def _airport(text: str | None, privacy: PrivacyManager) -> str | None:
    if not text:
        return None
    code = re.search(r"\b([A-Z]{3})\b", text)
    return code.group(1) if code else privacy.sanitize_text(text.strip())[:40]


def _departure(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.strip())
    except ValueError:
        return None


class ObservationEngine:
    def __init__(self, privacy: PrivacyManager | None = None) -> None:
        self.privacy = privacy or get_privacy_manager()
        self._salt = secrets.token_bytes(16)  # per-process: internal ids are not reversible

    def _internal_id(self, *parts: str | None) -> str:
        material = "|".join(p or "" for p in parts).encode()
        return hmac.new(self._salt, material, hashlib.sha256).hexdigest()[:16]

    def _register_pii(self, raw: RawPageObservation) -> None:
        self.privacy.register(raw.booking_reference_text, SensitiveKind.PNR)
        for row in raw.passenger_rows:
            self.privacy.register(row.name_text, SensitiveKind.NAME)
            self.privacy.register(row.ticket_text, SensitiveKind.TICKET)

    def _offer(
        self, raw: RawUpgradeOffer, n_rows: int, source: SnapshotSource
    ) -> UpgradeOption | None:
        cabin = parse_cabin(raw.cabin_text)
        if cabin is None:
            return None  # cannot tell which cabin the offer is for: ignore, don't guess
        price_text = raw.price_text
        free_label = bool(price_text and _FREE_WORDS.search(price_text)) and not parse_miles(
            price_text
        )
        cash = parse_money(price_text)
        miles = parse_miles(raw.miles_text) if raw.miles_text else parse_miles(price_text)
        if miles is None and free_label:
            miles = 0  # an explicit "free" label covers both cash and miles
        covered = parse_int(raw.passengers_text)
        if covered is None and re.search(
            r"(?i)tous les passagers|all passengers", raw.passengers_text or ""
        ):
            covered = n_rows
        availability = parse_availability(raw.availability_text)
        if availability is None and raw.availability_text is None and raw.has_accept_button:
            availability = True  # the official accept button is itself displayed
        return UpgradeOption(
            option_id=re.sub(r"[^A-Za-z0-9_-]", "", raw.offer_id)[:32] or "OFFER",
            cabin=cabin,
            cash_price=cash,
            currency="EUR" if cash is not None else None,
            miles_price=miles,
            passengers_covered=covered,
            availability=availability,
            actionable=raw.has_accept_button,
            source=source,
            label=self.privacy.sanitize_text(price_text or "")[:120] or None,
        )

    def build_snapshot(
        self,
        raw: RawPageObservation,
        *,
        source: SnapshotSource,
        confirmed_by_airline: bool,
    ) -> BookingSnapshot:
        self._register_pii(raw)
        page_state = _PAGE_STATES[raw.page_kind]
        messages = [self.privacy.sanitize_text(m)[:300] for m in raw.messages[:20]]
        if page_state is not PageState.BOOKING_VISIBLE:
            return BookingSnapshot(
                page_state=page_state,
                observed_messages=messages,
                source=source,
                confirmed_by_airline=False,
            )

        flight = None
        if raw.flight_number_text:
            flight = Flight(
                airline="AF",
                flight_number=re.sub(r"\s+", "", raw.flight_number_text.upper()),
                origin=_airport(raw.origin_text, self.privacy),
                destination=_airport(raw.destination_text, self.privacy),
                departure_datetime=_departure(raw.departure_text),
                aircraft=self.privacy.sanitize_text(raw.aircraft_text)
                if raw.aircraft_text
                else None,
            )

        options = [
            o
            for o in (self._offer(r, len(raw.passenger_rows), source) for r in raw.upgrade_offers)
            if o is not None
        ]
        # An official Business offer explicitly covering every listed passenger is an
        # observation of their eligibility (used only when no per-passenger text exists).
        group_offer = next(
            (
                o
                for o in options
                if o.cabin is Cabin.BUSINESS
                and o.availability is True
                and o.passengers_covered is not None
                and raw.passenger_rows
                and o.passengers_covered >= len(raw.passenger_rows)
            ),
            None,
        )

        passengers: list[Passenger] = []
        for index, row in enumerate(raw.passenger_rows, start=1):
            cabin = parse_cabin(row.cabin_text)
            eligibility = parse_eligibility(row.eligibility_text)
            if eligibility is not None:
                elig_obs = Observed[Eligibility].seen(eligibility, "per-passenger text")
            elif group_offer is not None:
                elig_obs = Observed[Eligibility].seen(
                    Eligibility.ELIGIBLE, f"covered by official offer {group_offer.option_id}"
                )
            else:
                elig_obs = Observed[Eligibility].unknown()
            seat = (row.seat_text or "").strip()
            passengers.append(
                Passenger(
                    internal_id=self._internal_id(
                        raw.booking_reference_text, row.name_text, str(index)
                    ),
                    anonymized_id=f"PASSENGER_{index:03d}",
                    current_cabin=Observed[Cabin].seen(cabin)
                    if cabin
                    else Observed[Cabin].unknown(),
                    current_seat=(
                        Observed[str].seen(seat)
                        if re.fullmatch(r"\d{1,2}[A-K]", seat)
                        else Observed[str].unknown()
                    ),
                    eligibility_status=elig_obs,
                )
            )

        count = parse_int(raw.passengers_count_text)
        if count is not None:
            passengers_count = Observed[int].seen(count, "passenger count text")
        elif passengers:
            passengers_count = Observed[int].seen(len(passengers), "passenger rows listed")
        else:
            passengers_count = Observed[int].unknown()

        cabin = parse_cabin(raw.cabin_text)
        row_cabins = {p.current_cabin.value for p in passengers if p.current_cabin.is_observed}
        if cabin is not None:
            current_cabin = Observed[Cabin].seen(cabin, "booking cabin text")
        elif (
            len(row_cabins) == 1
            and len(passengers)
            and all(p.current_cabin.is_observed for p in passengers)
        ):
            only = next(iter(row_cabins))
            current_cabin = (
                Observed[Cabin].seen(only, "all passenger rows")
                if only
                else Observed[Cabin].unknown()
            )
        else:
            current_cabin = Observed[Cabin].unknown()

        seats = parse_int(raw.business_seats_text)
        available = parse_availability(raw.business_availability_text)
        checkin = parse_checkin(raw.checkin_text)
        return BookingSnapshot(
            page_state=page_state,
            anonymized_booking_id=(
                self.privacy.redact_pnr(raw.booking_reference_text)
                if raw.booking_reference_text
                else None
            ),
            flight=flight,
            passengers_count=passengers_count,
            passengers=passengers,
            current_cabin=current_cabin,
            business_available=(
                Observed[bool].seen(available)
                if available is not None
                else Observed[bool].unknown()
            ),
            business_seats_visible=(
                Observed[int].seen(seats) if seats is not None else Observed[int].unknown()
            ),
            upgrade_options=options,
            checkin_status=(
                Observed[CheckinStatus].seen(checkin)
                if checkin is not None
                else Observed[CheckinStatus].unknown()
            ),
            observed_messages=messages,
            source=source,
            confirmed_by_airline=confirmed_by_airline,
        )
