"""Price watch: polite rotation, alerts, dedup, passengers option, Duffel parsing."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.notifications.service import NotificationEvent
from app.pricewatch.engine import default_watches
from app.pricewatch.models import AlertKind, FareCabin, PriceWatch
from app.pricewatch.providers import DuffelFareProvider, FareSourceError, MockFareProvider
from app.services.container import Container

TODAY = date(2026, 10, 7)


def _container(provider: MockFareProvider | None = None, **kw: object) -> Container:
    settings = Settings(database_url="sqlite://", _env_file=None, **kw)  # type: ignore[call-arg]
    return Container.build(settings, fare_provider=provider or MockFareProvider())


def _watch(**kw: object) -> PriceWatch:
    base: dict[str, object] = {
        "name": "Dakar ↔ Paris",
        "origin": "DSS",
        "destinations": ["CDG"],
        "depart_from": TODAY + timedelta(days=10),
        "depart_to": TODAY + timedelta(days=12),
        "trip_length_days": 14,
        "passengers": 1,
        "airlines": ["AF"],
    }
    base.update(kw)
    return PriceWatch.model_validate(base)


def test_watch_validation_and_passengers_option() -> None:
    w = _watch(origin="dss", destinations=["cdg", "CDG"], passengers=2)
    assert w.origin == "DSS" and w.destinations == ["CDG"] and w.passengers == 2
    for bad in (
        {"passengers": 0},
        {"passengers": 10},
        {"destinations": ["PARIS"]},
        {"destinations": ["DSS"]},
        {"depart_to": TODAY},
    ):
        with pytest.raises(ValidationError):
            _watch(**bad)


def test_default_watches_match_request() -> None:
    dakar, europe = default_watches(TODAY)
    assert (dakar.origin, dakar.destinations, dakar.round_trip) == ("DSS", ["CDG"], True)
    assert dakar.passengers == 1
    assert europe.origin == "CDG" and len(europe.destinations) >= 6
    assert europe.trip_length_days == 3 and europe.max_total_price == 150


def test_sample_dates_are_bounded() -> None:
    w = _watch(depart_from=TODAY + timedelta(days=1), depart_to=TODAY + timedelta(days=100))
    dates = w.sample_dates(7, TODAY)
    assert len(dates) == 7 and dates[0] == TODAY + timedelta(days=1)
    assert dates[-1] == TODAY + timedelta(days=100)
    past = _watch(depart_from=TODAY - timedelta(days=9), depart_to=TODAY - timedelta(days=2))
    assert past.sample_dates(7, TODAY) == []


async def test_rotation_limits_searches_per_check() -> None:
    provider = MockFareProvider()
    c = _container(provider, max_dates_per_watch=3)
    watch = c.pricewatch.add_watch(
        _watch(
            origin="CDG",
            destinations=["LIS", "BCN"],
            airlines=[],
            depart_to=TODAY + timedelta(days=30),
        )
    )
    seen: set[tuple[str, date]] = set()
    for _ in range(2):
        result = await c.pricewatch.check_watch(watch.watch_id, today=TODAY)
        assert result.searches == 3
        seen |= {(q.destination, q.depart_date) for q in result.quotes}
    assert provider.calls == 6
    assert len(seen) == 6  # second check continued where the first stopped


async def test_below_threshold_alert_once_then_only_if_lower() -> None:
    provider = MockFareProvider()
    c = _container(provider, max_dates_per_watch=1)
    d = TODAY + timedelta(days=10)
    w = c.pricewatch.add_watch(_watch(depart_to=d, max_total_price=Decimal(500)))
    provider.set_price("CDG", d, Decimal(480))

    first = await c.pricewatch.check_watch(w.watch_id, today=TODAY)
    assert [a.kind for a in first.alerts] == [AlertKind.BELOW_THRESHOLD]
    alert = first.alerts[0]
    assert alert.booking_url == "https://wwws.airfrance.fr/"
    assert "480 EUR pour 1 passager" in alert.message
    assert c.notifier.recent(1)[0].event is NotificationEvent.PRICE_ALERT

    again = await c.pricewatch.check_watch(w.watch_id, today=TODAY)
    assert again.alerts == []  # same price: no spam

    provider.set_price("CDG", d, Decimal(430))
    lower = await c.pricewatch.check_watch(w.watch_id, today=TODAY)
    assert len(lower.alerts) == 1


async def test_price_drop_and_new_low() -> None:
    provider = MockFareProvider()
    c = _container(provider, max_dates_per_watch=1, price_drop_alert_percent=Decimal(10))
    d = TODAY + timedelta(days=10)
    w = c.pricewatch.add_watch(_watch(depart_to=d))
    for price in (700, 690, 695):
        provider.set_price("CDG", d, Decimal(price))
        assert (await c.pricewatch.check_watch(w.watch_id, today=TODAY)).alerts == []
    provider.set_price("CDG", d, Decimal(600))
    result = await c.pricewatch.check_watch(w.watch_id, today=TODAY)
    assert [a.kind for a in result.alerts] == [AlertKind.NEW_LOW]
    assert result.alerts[0].previous_price == 690


async def test_passengers_multiply_total_and_airline_filter() -> None:
    provider = MockFareProvider()
    c = _container(provider, max_dates_per_watch=1)
    d = TODAY + timedelta(days=10)
    provider.set_price("CDG", d, Decimal(300))
    w3 = c.pricewatch.add_watch(_watch(depart_to=d, passengers=3))
    quote = (await c.pricewatch.check_watch(w3.watch_id, today=TODAY)).quotes[0]
    assert quote.total_price == 900 and quote.price_per_passenger == 300
    other = c.pricewatch.add_watch(_watch(depart_to=d, airlines=["XX"]))
    assert (await c.pricewatch.check_watch(other.watch_id, today=TODAY)).quotes == []


async def test_source_errors_are_reported_not_guessed() -> None:
    class Failing(MockFareProvider):
        async def search(self, **kw: object):  # type: ignore[no-untyped-def,override]
            raise FareSourceError("Fare source rate limit reached")

    c = _container(Failing())
    w = c.pricewatch.add_watch(_watch())
    result = await c.pricewatch.check_watch(w.watch_id, today=TODAY)
    assert result.quotes == [] and result.alerts == []
    assert len(result.errors) == 1  # stopped at the first rate-limit


def test_interval_never_below_one_hour() -> None:
    with pytest.raises(ValidationError):
        Settings(price_watch_interval_seconds=60, _env_file=None)  # type: ignore[call-arg]


async def test_duffel_request_and_parsing() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers["Authorization"]
        captured["version"] = request.headers["Duffel-Version"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "data": {
                    "offers": [
                        {
                            "total_amount": "1234.50",
                            "total_currency": "EUR",
                            "owner": {"iata_code": "AF"},
                            "slices": [
                                {
                                    "segments": [
                                        {
                                            "marketing_carrier": {"iata_code": "AF"},
                                            "marketing_carrier_flight_number": "719",
                                        }
                                    ]
                                }
                            ],
                        },
                        {"total_currency": "EUR"},  # unpriced: ignored
                    ]
                }
            },
        )

    provider = DuffelFareProvider("tok", transport=httpx.MockTransport(handler))
    quotes = await provider.search(
        origin="DSS",
        destination="CDG",
        depart_date=TODAY,
        return_date=TODAY + timedelta(days=14),
        passengers=2,
        cabin=FareCabin.ECONOMY,
    )
    assert captured["auth"] == "Bearer tok" and captured["version"] == "v2"
    body = captured["body"]
    assert isinstance(body, dict)
    assert len(body["data"]["slices"]) == 2 and len(body["data"]["passengers"]) == 2
    assert len(quotes) == 1
    assert quotes[0].total_price == Decimal("1234.50") and quotes[0].flight_numbers == ["AF719"]


async def test_duffel_rate_limit() -> None:
    provider = DuffelFareProvider(
        "tok", transport=httpx.MockTransport(lambda r: httpx.Response(429))
    )
    with pytest.raises(FareSourceError, match="rate limit"):
        await provider.search(
            origin="DSS",
            destination="CDG",
            depart_date=TODAY,
            return_date=None,
            passengers=1,
            cabin=FareCabin.ECONOMY,
        )


def test_api_end_to_end_and_upgrade_passengers_option() -> None:
    c = _container()
    with TestClient(create_app(c.settings, c)) as client:
        names = [s["watch"]["name"] for s in client.get("/api/pricewatch/watches").json()]
        assert names == ["Dakar ↔ Paris", "Escapades Europe"]  # seeded defaults
        new = client.post(
            "/api/pricewatch/watches",
            json={
                "name": "Week-end Lisbonne",
                "origin": "CDG",
                "destinations": ["LIS"],
                "depart_from": str(date.today() + timedelta(days=5)),
                "depart_to": str(date.today() + timedelta(days=20)),
                "trip_length_days": 2,
                "passengers": 2,
                "airlines": [],
            },
        )
        assert new.status_code == 201
        wid = new.json()["watch_id"]
        check = client.post(f"/api/pricewatch/watches/{wid}/check").json()
        assert check["searches"] > 0 and check["quotes"]
        assert client.get(f"/api/pricewatch/watches/{wid}/history").json()
        assert client.delete(f"/api/pricewatch/watches/{wid}").json() == {"deleted": True}
        assert client.post("/api/pricewatch/watches", json={"name": "x"}).status_code == 422

        # Upgrade module: passenger count is now an option (1 to 9).
        r = client.put(
            "/api/settings/limits", json={"cash_limit": 0, "miles_limit": 0, "passengers_target": 2}
        )
        assert r.json()["passengers_target"] == 2
        assert client.post("/api/check").json()["decision"]["passengers_target"] == 2
        bad = client.put(
            "/api/settings/limits", json={"cash_limit": 0, "miles_limit": 0, "passengers_target": 0}
        )
        assert bad.status_code == 422
