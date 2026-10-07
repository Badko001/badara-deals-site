"""Several bookings: isolation, privacy of references, per-booking passengers, safety."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import DecisionStatus, PageState
from app.services.db import Database
from tests.conftest import make_container


async def test_bookings_are_watched_independently() -> None:
    c = make_container("free_upgrade_3_business")
    other = c.bookings.add("Vacances Noël", None, passengers_target=2, mock_scenario="paid_upgrade")
    ctx_a, ctx_b = c.bookings.first(), c.bookings.context(other.booking_id)

    a = await ctx_a.monitoring.check_once()
    b = await ctx_b.monitoring.check_once()
    assert a.decision.status is DecisionStatus.OPPORTUNITY
    assert b.decision.status is DecisionStatus.NO_OPPORTUNITY
    assert b.decision.passengers_target == 2
    assert ctx_a.confirmations.current_pending() is not None
    assert ctx_b.confirmations.current_pending() is None
    assert a.notifications[0].message.startswith("[Ma réservation]")


async def test_confirmation_belongs_to_its_booking() -> None:
    c = make_container()
    other = c.bookings.add("Autre", None, passengers_target=3)
    await c.bookings.first().monitoring.check_once()
    await c.bookings.context(other.booking_id).monitoring.check_once()
    pending_a = c.bookings.first().confirmations.current_pending()
    pending_b = c.bookings.context(other.booking_id).confirmations.current_pending()
    assert pending_a is not None and pending_b is not None
    assert pending_a.confirmation_id != pending_b.confirmation_id
    # A request of booking B cannot be confirmed through booking A.
    from app.errors import HumanConfirmationRequired

    with pytest.raises(HumanConfirmationRequired):
        c.bookings.first().confirmations.confirm(pending_b.confirmation_id)
    ctx = c.bookings.context_for_confirmation(pending_b.confirmation_id)
    assert ctx is not None and ctx.info.booking_id == other.booking_id


def test_full_reference_is_never_stored(tmp_path: Path) -> None:
    db_file = tmp_path / "agent.db"
    c = make_container(database_url=f"sqlite:///{db_file}")
    info = c.bookings.add("Paris juin", "xyz789", passengers_target=1)
    assert info.reference_redacted == "PNR_****789"
    assert info.reference_in_memory is True
    assert c.bookings.reference(info.booking_id) == "XYZ789"
    dump = b"".join(Path(p).read_bytes() for p in [db_file] if Path(p).exists())
    assert b"XYZ789" not in dump and b"xyz789" not in dump

    # After a "restart" the redacted reference remains, the full one must be typed again.
    c2 = make_container(database_url=f"sqlite:///{db_file}")
    again = c2.bookings.get(info.booking_id)
    assert again.reference_redacted == "PNR_****789" and again.reference_in_memory is False


def test_invalid_reference_rejected() -> None:
    c = make_container()
    with pytest.raises(ValueError):
        c.bookings.add("x", "AB", passengers_target=1)


async def test_other_booking_displayed_is_never_attributed() -> None:
    c = make_container()
    info = c.bookings.add("Résa A", "ABC456", passengers_target=3)
    mock = c.bookings.mock(info.booking_id)
    assert mock is not None
    mock.reference = "ZZZ999"  # the airline page now shows another booking
    mock.set_scenario("free_upgrade_3_business")
    result = await c.bookings.context(info.booking_id).monitoring.check_once()
    assert result.snapshot.page_state is PageState.BOOKING_NOT_FOUND
    assert result.decision.status is DecisionStatus.ACTION_REQUIRED
    assert result.snapshot.upgrade_options == []


async def test_delete_rules() -> None:
    c = make_container()
    with pytest.raises(ValueError):
        await c.bookings.delete(c.bookings.first().info.booking_id)  # last one
    extra = c.bookings.add("Temp", None, passengers_target=1)
    await c.bookings.delete(extra.booking_id)
    assert [x.info.booking_id for x in c.bookings.all()] == ["default"]


def test_old_database_is_migrated(tmp_path: Path) -> None:
    db_file = tmp_path / "old.db"
    con = sqlite3.connect(db_file)
    con.execute(
        "CREATE TABLE confirmations (confirmation_id VARCHAR(64) PRIMARY KEY, option_id VARCHAR(64),"
        " snapshot_id VARCHAR(64), state VARCHAR(16), max_cash VARCHAR(32), max_miles INTEGER,"
        " passengers INTEGER, created_at DATETIME, expires_at DATETIME, decided_at DATETIME,"
        " summary JSON)"
    )
    con.commit()
    con.close()
    Database(f"sqlite:///{db_file}")
    columns = {
        row[1] for row in sqlite3.connect(db_file).execute("PRAGMA table_info(confirmations)")
    }
    assert "booking_id" in columns


def test_bookings_api() -> None:
    c = make_container()
    with TestClient(create_app(c.settings, c)) as client:
        created = client.post(
            "/api/bookings",
            json={
                "label": "Dakar août",
                "reference": "QWE123",
                "passengers_target": 2,
                "mock_scenario": "two_business_available",
            },
        )
        assert created.status_code == 201
        body = created.json()
        bid = body["booking_id"]
        assert body["reference_redacted"] == "PNR_****123" and "QWE123" not in created.text

        check = client.post(f"/api/check?booking_id={bid}").json()
        assert check["decision"]["passengers_target"] == 2
        dash = client.get(f"/api/dashboard?booking_id={bid}").json()
        assert dash["booking"]["label"] == "Dakar août"
        assert dash["config"]["mock_scenario"] == "two_business_available"
        assert len(dash["bookings"]) == 2
        assert "QWE123" not in client.get("/api/audit").text

        r = client.put(
            f"/api/settings/limits?booking_id={bid}",
            json={"cash_limit": 0, "miles_limit": 0, "passengers_target": 1},
        )
        assert r.json()["passengers_target"] == 1
        # The other booking keeps its own passenger count.
        assert client.get("/api/settings/limits").json()["passengers_target"] == 3

        assert (
            client.patch(f"/api/bookings/{bid}", json={"label": "Dakar"}).json()["label"] == "Dakar"
        )
        assert client.get("/api/dashboard?booking_id=nope").status_code == 404
        assert (
            client.post("/api/bookings", json={"label": "x", "reference": "!!"}).status_code == 422
        )
        assert client.delete(f"/api/bookings/{bid}").json() == {"deleted": True}
        assert client.delete("/api/bookings/default").status_code == 409
