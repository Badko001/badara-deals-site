"""End-to-end through the HTTP API on MOCK AIR FRANCE."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_container


def _client(scenario: str = "free_upgrade_3_business", **kw: object) -> TestClient:
    container = make_container(scenario, **kw)
    return TestClient(create_app(container.settings, container))


def test_full_flow_dry_run() -> None:
    with _client() as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        check = client.post("/api/check").json()
        assert check["decision"]["status"] == "OPPORTUNITY"
        assert check["decision"]["cash_cost"] == 0

        dash = client.get("/api/dashboard").json()
        assert dash["config"]["dry_run"] is True
        assert dash["flight"]["flight_number"] == "AF719"
        assert dash["flight"]["anonymized_booking_id"] == "PNR_****123"
        pending = dash["pending_confirmation"]
        assert pending["summary"]["origin"] == "DSS"

        result = client.post(f"/api/confirmations/{pending['confirmation_id']}/confirm").json()
        assert result["status"] == "DRY_RUN_SIMULATED"

        again = client.post(f"/api/confirmations/{pending['confirmation_id']}/confirm")
        assert again.status_code == 409

        audit = client.get("/api/audit").text
        for pii in ("TEST123", "Awa", "TESTDIOP", "0570000000001"):
            assert pii not in audit
        events = {e["event_type"] for e in client.get("/api/audit").json()}
        assert {"CHECK", "HUMAN_CONFIRMED", "UPGRADE_EXECUTION"} <= events


def test_decline_endpoint() -> None:
    with _client() as client:
        client.post("/api/check")
        pending = client.get("/api/dashboard").json()["pending_confirmation"]
        body = client.post(f"/api/confirmations/{pending['confirmation_id']}/decline").json()
        assert body["status"] == "DECLINED"
        assert client.get("/api/dashboard").json()["pending_confirmation"] is None


def test_limits_are_editable_at_runtime() -> None:
    with _client("paid_upgrade") as client:
        assert client.post("/api/check").json()["decision"]["status"] == "NO_OPPORTUNITY"
        assert (
            client.put(
                "/api/settings/limits", json={"cash_limit": 800, "miles_limit": 0}
            ).status_code
            == 200
        )
        assert client.post("/api/check").json()["decision"]["status"] == "OPPORTUNITY"
        assert (
            client.put(
                "/api/settings/limits", json={"cash_limit": -1, "miles_limit": 0}
            ).status_code
            == 422
        )


def test_mock_scenarios_endpoints() -> None:
    with _client() as client:
        scenarios = client.get("/api/mock/scenarios").json()
        assert "paid_upgrade" in scenarios["scenarios"]
        assert client.post("/api/mock/scenario", json={"name": "captcha"}).status_code == 200
        assert client.post("/api/check").json()["decision"]["status"] == "ACTION_REQUIRED"
        assert client.post("/api/mock/scenario", json={"name": "nope"}).status_code == 404
        assert "SIMULATION" in client.get("/api/mock/page").text
