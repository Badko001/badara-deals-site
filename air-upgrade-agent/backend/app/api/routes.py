"""REST API consumed by the dashboard."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.api.schemas import (
    CheckResponse,
    DashboardResponse,
    FlightView,
    LimitsUpdate,
    PassengerView,
    RuntimeConfig,
    ScenarioUpdate,
    SessionStart,
)
from app.booking.providers.airfrance import AirFranceProvider
from app.browser.mock_page import render_mock_page
from app.models import BookingSnapshot, CostLimits
from app.models.actions import UpgradeExecutionResult
from app.monitoring.engine import MonitoringState
from app.security.privacy import SensitiveKind, get_privacy_manager
from app.services.audit import AuditEvent
from app.services.container import Container

router = APIRouter(prefix="/api")


def _c(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


def _flight_view(snapshot: BookingSnapshot | None) -> FlightView | None:
    if snapshot is None:
        return None
    flight = snapshot.flight
    return FlightView(
        anonymized_booking_id=snapshot.anonymized_booking_id,
        flight_number=flight.flight_number if flight else None,
        origin=flight.origin if flight else None,
        destination=flight.destination if flight else None,
        departure_datetime=flight.departure_datetime if flight else None,
        current_cabin=snapshot.current_cabin.value.value if snapshot.current_cabin.value else None,
        passengers=[
            PassengerView(
                anonymized_id=p.anonymized_id,
                current_cabin=p.current_cabin.value.value if p.current_cabin.value else None,
                eligibility=p.eligibility_status.value.value
                if p.eligibility_status.value
                else None,
            )
            for p in snapshot.passengers
        ],
        business_available=snapshot.business_available.observed_value,
        business_seats_visible=snapshot.business_seats_visible.observed_value,
        business_seats_provenance=snapshot.business_seats_visible.provenance.value,
        checkin_status=snapshot.checkin_status.value.value
        if snapshot.checkin_status.value
        else None,
        observed_messages=snapshot.observed_messages,
        confirmed_by_airline=snapshot.confirmed_by_airline,
        snapshot_time=snapshot.timestamp,
    )


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(request: Request) -> DashboardResponse:
    c = _c(request)
    return DashboardResponse(
        config=RuntimeConfig(
            dry_run=c.settings.dry_run,
            debug_mode=c.settings.debug_mode,
            provider=c.provider.name,
            llm_enabled=c.orchestrator.enabled,
            mock_scenario=c.mock.scenario_name if c.mock else None,
            session_ready=c.provider.session_ready,
        ),
        limits=c.runtime.get_limits(),
        monitoring=c.monitoring.state,
        flight=_flight_view(c.monitoring.last_snapshot),
        decision=c.monitoring.last_decision,
        pending_confirmation=c.confirmations.current_pending(),
        last_execution=c.last_execution,
        notifications=c.notifier.recent(10),
    )


@router.post("/check", response_model=CheckResponse)
async def check_now(request: Request) -> CheckResponse:
    result = await _c(request).monitoring.check_once()
    return CheckResponse(
        decision=result.decision, changes=result.changes, notifications=result.notifications
    )


@router.post("/monitoring/start", response_model=MonitoringState)
async def start_monitoring(request: Request) -> MonitoringState:
    c = _c(request)
    await c.monitoring.start_monitoring()
    return c.monitoring.state


@router.post("/monitoring/stop", response_model=MonitoringState)
async def stop_monitoring(request: Request) -> MonitoringState:
    c = _c(request)
    await c.monitoring.stop_monitoring()
    return c.monitoring.state


@router.post("/confirmations/{confirmation_id}/confirm", response_model=UpgradeExecutionResult)
async def confirm(confirmation_id: str, request: Request) -> UpgradeExecutionResult:
    c = _c(request)
    result = await c.executor.confirm_and_execute(confirmation_id, c.runtime.get_limits())
    c.last_execution = result
    return result


@router.post("/confirmations/{confirmation_id}/decline")
async def decline(confirmation_id: str, request: Request) -> dict[str, str]:
    _c(request).executor.decline(confirmation_id)
    return {"status": "DECLINED", "message": "Aucune action effectuée."}


@router.get("/notifications")
async def notifications(request: Request) -> list[dict[str, Any]]:
    return [n.model_dump(mode="json") for n in _c(request).notifier.recent(50)]


@router.get("/audit", response_model=list[AuditEvent])
async def audit(request: Request, limit: int = 50) -> list[AuditEvent]:
    return _c(request).audit.recent(min(limit, 200))


@router.get("/settings/limits", response_model=CostLimits)
async def get_limits(request: Request) -> CostLimits:
    return _c(request).runtime.get_limits()


@router.put("/settings/limits", response_model=CostLimits)
async def set_limits(body: LimitsUpdate, request: Request) -> CostLimits:
    c = _c(request)
    limits = c.runtime.set_limits(body.cash_limit, body.miles_limit, body.passengers_target)
    c.audit.record(
        "LIMITS_CHANGED",
        action="update limits",
        result=(
            f"cash_limit={limits.cash_limit} miles_limit={limits.miles_limit} "
            f"passengers_target={limits.passengers_target}"
        ),
    )
    return limits


@router.post("/session/start")
async def session_start(body: SessionStart, request: Request) -> dict[str, Any]:
    """Opens the isolated browser. The USER logs in there by hand - never via this API."""
    c = _c(request)
    if isinstance(c.provider, AirFranceProvider):
        if body.booking_hint:
            get_privacy_manager().register(body.booking_hint, SensitiveKind.PNR)
            c.provider.booking_hint = body.booking_hint
        await c.provider.start()
    c.audit.record("SESSION_START", action="open isolated browser", result=c.provider.name)
    return {"provider": c.provider.name, "session_ready": c.provider.session_ready}


@router.post("/session/close")
async def session_close(request: Request) -> dict[str, Any]:
    c = _c(request)
    await c.monitoring.stop_monitoring()
    await c.provider.close()
    c.audit.record("SESSION_CLOSE", action="close browser, discard session")
    return {"session_ready": c.provider.session_ready}


@router.get("/mock/scenarios")
async def mock_scenarios(request: Request) -> dict[str, Any]:
    c = _c(request)
    if c.mock is None:
        raise HTTPException(404, "Mock provider not active")
    return {
        "current": c.mock.scenario_name,
        "scenarios": {name: s.description for name, s in c.mock.scenarios.items()},
    }


@router.post("/mock/scenario")
async def set_mock_scenario(body: ScenarioUpdate, request: Request) -> dict[str, str]:
    c = _c(request)
    if c.mock is None:
        raise HTTPException(404, "Mock provider not active")
    try:
        c.mock.set_scenario(body.name)
    except KeyError as exc:
        raise HTTPException(404, "Unknown scenario") from exc
    c.audit.record("MOCK_SCENARIO", action=body.name)
    return {"current": body.name}


@router.get("/mock/page", response_class=HTMLResponse)
async def mock_page(request: Request) -> HTMLResponse:
    """The simulated airline page, for demos. Mock mode only."""
    c = _c(request)
    if c.mock is None:
        raise HTTPException(404, "Mock provider not active")
    return HTMLResponse(render_mock_page(c.mock.current_page()))
