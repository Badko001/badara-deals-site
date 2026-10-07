"""Fare sources. Only authorised APIs or the local simulation - never scraping."""

from __future__ import annotations

import hashlib
import logging
from datetime import date
from decimal import Decimal
from typing import Any, Protocol

import httpx

from app.errors import AirUpgradeError
from app.pricewatch.models import FareCabin, FareQuote

logger = logging.getLogger(__name__)


class FareSourceError(AirUpgradeError):
    critical = False


class FareProvider(Protocol):
    name: str

    async def search(
        self,
        *,
        origin: str,
        destination: str,
        depart_date: date,
        return_date: date | None,
        passengers: int,
        cabin: FareCabin,
    ) -> list[FareQuote]: ...


# ----------------------------------------------------------------- simulation
#: Typical round-trip price per passenger in economy (fictitious, for the simulation).
_BASE_PRICES = {
    ("DSS", "CDG"): Decimal(620),
    ("CDG", "DSS"): Decimal(620),
    ("CDG", "LIS"): Decimal(160),
    ("CDG", "BCN"): Decimal(140),
    ("CDG", "FCO"): Decimal(170),
    ("CDG", "AMS"): Decimal(130),
    ("CDG", "ATH"): Decimal(210),
    ("CDG", "MAD"): Decimal(150),
    ("CDG", "PRG"): Decimal(165),
    ("CDG", "OPO"): Decimal(145),
}
_CABIN_FACTOR = {
    FareCabin.ECONOMY: Decimal(1),
    FareCabin.PREMIUM_ECONOMY: Decimal("1.8"),
    FareCabin.BUSINESS: Decimal("3.5"),
    FareCabin.FIRST: Decimal(6),
}
_CARRIER = {"DSS": "AF", "CDG": "AF", "AMS": "KL", "LIS": "TO", "OPO": "TO", "BCN": "TO"}


def seed_number(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:2], "big")


class MockFareProvider:
    """Deterministic fictitious fares. Tests and demos can move prices."""

    name = "mock"

    def __init__(self) -> None:
        self.market_factor = Decimal(1)
        self.overrides: dict[tuple[str, date], Decimal] = {}  # per-passenger price
        self.calls = 0

    def set_price(self, destination: str, depart: date, per_passenger: Decimal) -> None:
        self.overrides[(destination, depart)] = per_passenger

    async def search(
        self,
        *,
        origin: str,
        destination: str,
        depart_date: date,
        return_date: date | None,
        passengers: int,
        cabin: FareCabin,
    ) -> list[FareQuote]:
        self.calls += 1
        per_pax = self.overrides.get((destination, depart_date))
        if per_pax is None:
            base = _BASE_PRICES.get((origin, destination), Decimal(250))
            seed = hashlib.sha256(f"{origin}{destination}{depart_date}".encode()).digest()[0]
            variation = Decimal("0.75") + Decimal(seed) / Decimal(255) * Decimal("0.6")
            one_way = Decimal("0.6") if return_date is None else Decimal(1)
            per_pax = base * variation * one_way * _CABIN_FACTOR[cabin] * self.market_factor
        carrier = _CARRIER.get(destination, _CARRIER.get(origin, "AF"))
        return [
            FareQuote(
                destination=destination,
                depart_date=depart_date,
                return_date=return_date,
                total_price=(per_pax * passengers).quantize(Decimal(1)),
                currency="EUR",
                carrier=carrier,
                flight_numbers=[f"{carrier}{1000 + seed_number(destination) % 900}"],
                cabin=cabin,
                passengers=passengers,
                source="SIMULATION",
            )
        ]


# ----------------------------------------------------------------- Duffel API
class DuffelFareProvider:
    """Published offers through the Duffel API (requires your own API token).

    TODO(verify): written against Duffel's public documentation (offer requests,
    API version v2) but not yet exercised with a real token in this project.
    """

    name = "duffel"
    URL = "https://api.duffel.com/air/offer_requests"

    def __init__(self, token: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Duffel-Version": "v2",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._transport = transport

    async def search(
        self,
        *,
        origin: str,
        destination: str,
        depart_date: date,
        return_date: date | None,
        passengers: int,
        cabin: FareCabin,
    ) -> list[FareQuote]:
        slices = [
            {
                "origin": origin,
                "destination": destination,
                "departure_date": depart_date.isoformat(),
            }
        ]
        if return_date is not None:
            slices.append(
                {
                    "origin": destination,
                    "destination": origin,
                    "departure_date": return_date.isoformat(),
                }
            )
        body = {
            "data": {
                "slices": slices,
                "passengers": [{"type": "adult"} for _ in range(passengers)],
                "cabin_class": cabin.value,
            }
        }
        try:
            async with httpx.AsyncClient(timeout=60, transport=self._transport) as client:
                response = await client.post(
                    self.URL, params={"return_offers": "true"}, json=body, headers=self._headers
                )
        except httpx.HTTPError as exc:
            raise FareSourceError("Fare source unreachable") from exc
        if response.status_code == 429:
            raise FareSourceError("Fare source rate limit reached")
        if response.status_code >= 400:
            raise FareSourceError(f"Fare source error HTTP {response.status_code}")
        return self._parse(
            response.json(), destination, depart_date, return_date, passengers, cabin
        )

    @staticmethod
    def _parse(
        payload: dict[str, Any],
        destination: str,
        depart_date: date,
        return_date: date | None,
        passengers: int,
        cabin: FareCabin,
    ) -> list[FareQuote]:
        quotes: list[FareQuote] = []
        for offer in payload.get("data", {}).get("offers", []):
            try:
                amount = Decimal(str(offer["total_amount"]))
                currency = str(offer["total_currency"])
            except (KeyError, ArithmeticError):
                continue  # unpriced offer: ignored, never guessed
            flights = [
                f"{seg.get('marketing_carrier', {}).get('iata_code', '')}{seg.get('marketing_carrier_flight_number', '')}"
                for sl in offer.get("slices", [])
                for seg in sl.get("segments", [])
            ]
            quotes.append(
                FareQuote(
                    destination=destination,
                    depart_date=depart_date,
                    return_date=return_date,
                    total_price=amount,
                    currency=currency,
                    carrier=(offer.get("owner") or {}).get("iata_code"),
                    flight_numbers=[f for f in flights if f],
                    cabin=cabin,
                    passengers=passengers,
                    source="DUFFEL",
                )
            )
        return quotes
