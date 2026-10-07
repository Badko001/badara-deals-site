"""REST API consumed by the dashboard."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from app.api.schemas import (
    BookingCreate,
    BookingUpdate,
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
from app.services.bookings import BookingContext, BookingInfo, BookingSummary
from app.services.container import Container

router = APIRouter(prefix="/api")


def _c(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


BookingQuery = Query(default=None, description="Booking to act on (default: the first one)")


def _ctx(request: Request, booking_id: str | None) -> BookingContext:
    try:
        return _c(request).bookings.context(booking_id)
    except KeyError as exc:
        raise HTTPException(404, "Unknown booking") from exc


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


# ------------------------------------------------------------------ bookings
@router.get("/bookings", response_model=list[BookingSummary])
async def list_bookings(request: Request) -> list[BookingSummary]:
    return _c(request).bookings.summaries()


@router.post("/bookings", response_model=BookingInfo, status_code=201)
async def add_booking(body: BookingCreate, request: Request) -> BookingInfo:
    c = _c(request)
    if body.mock_scenario and c.mock is not None and body.mock_scenario not in c.mock.scenarios:
        raise HTTPException(404, "Unknown scenario")
    try:
        return c.bookings.add(
            body.label, body.reference, body.passengers_target, body.mock_scenario
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.patch("/bookings/{booking_id}", response_model=BookingInfo)
async def update_booking(booking_id: str, body: BookingUpdate, request: Request) -> BookingInfo:
    _ctx(request, booking_id)
    try:
        return _c(request).bookings.update(
            booking_id,
            label=body.label,
            reference=body.reference,
            passengers_target=body.passengers_target,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/bookings/{booking_id}")
async def delete_booking(booking_id: str, request: Request) -> dict[str, bool]:
    _ctx(request, booking_id)
    try:
        await _c(request).bookings.delete(booking_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"deleted": True}


# ------------------------------------------------------------------ per booking
@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(request: Request, booking_id: str | None = BookingQuery) -> DashboardResponse:
    c = _c(request)
    ctx = _ctx(request, booking_id)
    mock = c.bookings.mock(ctx.info.booking_id)
    return DashboardResponse(
        booking=c.bookings.get(ctx.info.booking_id),
        bookings=c.bookings.summaries(),
        config=RuntimeConfig(
            dry_run=c.settings.dry_run,
            debug_mode=c.settings.debug_mode,
            provider=c.provider.name,
            llm_enabled=c.orchestrator.enabled,
            mock_scenario=mock.scenario_name if mock else None,
            session_ready=c.provider.session_ready,
        ),
        limits=c.bookings.limits_for(ctx.info.booking_id),
        monitoring=ctx.monitoring.state,
        flight=_flight_view(ctx.monitoring.last_snapshot),
        decision=ctx.monitoring.last_decision,
        pending_confirmation=ctx.confirmations.current_pending(),
        last_execution=ctx.last_execution,
        notifications=c.notifier.recent(10),
    )


@router.post("/check", response_model=CheckResponse)
async def check_now(request: Request, booking_id: str | None = BookingQuery) -> CheckResponse:
    result = await _ctx(request, booking_id).monitoring.check_once()
    return CheckResponse(
        decision=result.decision, changes=result.changes, notifications=result.notifications
    )


@router.post("/monitoring/start", response_model=MonitoringState)
async def start_monitoring(
    request: Request, booking_id: str | None = BookingQuery
) -> MonitoringState:
    ctx = _ctx(request, booking_id)
    await ctx.monitoring.start_monitoring()
    return ctx.monitoring.state


@router.post("/monitoring/stop", response_model=MonitoringState)
async def stop_monitoring(
    request: Request, booking_id: str | None = BookingQuery
) -> MonitoringState:
    ctx = _ctx(request, booking_id)
    await ctx.monitoring.stop_monitoring()
    return ctx.monitoring.state


def _ctx_for_confirmation(request: Request, confirmation_id: str) -> BookingContext:
    ctx = _c(request).bookings.context_for_confirmation(confirmation_id)
    if ctx is None:
        raise HTTPException(409, "No pending confirmation with this id")
    return ctx


@router.post("/confirmations/{confirmation_id}/confirm", response_model=UpgradeExecutionResult)
async def confirm(confirmation_id: str, request: Request) -> UpgradeExecutionResult:
    c = _c(request)
    ctx = _ctx_for_confirmation(request, confirmation_id)
    result = await ctx.executor.confirm_and_execute(
        confirmation_id, c.bookings.limits_for(ctx.info.booking_id)
    )
    ctx.last_execution = result
    return result


@router.post("/confirmations/{confirmation_id}/decline")
async def decline(confirmation_id: str, request: Request) -> dict[str, str]:
    _ctx_for_confirmation(request, confirmation_id).executor.decline(confirmation_id)
    return {"status": "DECLINED", "message": "Aucune action effectuée."}


@router.get("/notifications")
async def notifications(request: Request) -> list[dict[str, Any]]:
    return [n.model_dump(mode="json") for n in _c(request).notifier.recent(50)]


@router.get("/audit", response_model=list[AuditEvent])
async def audit(request: Request, limit: int = 50) -> list[AuditEvent]:
    return _c(request).audit.recent(min(limit, 200))


@router.get("/settings/limits", response_model=CostLimits)
async def get_limits(request: Request, booking_id: str | None = BookingQuery) -> CostLimits:
    return _c(request).bookings.limits_for(_ctx(request, booking_id).info.booking_id)


@router.put("/settings/limits", response_model=CostLimits)
async def set_limits(
    body: LimitsUpdate, request: Request, booking_id: str | None = BookingQuery
) -> CostLimits:
    """Cash / Miles limits are global; the passenger count belongs to the booking."""
    c = _c(request)
    ctx = _ctx(request, booking_id)
    c.runtime.set_limits(body.cash_limit, body.miles_limit)
    if body.passengers_target is not None:
        c.bookings.update(ctx.info.booking_id, passengers_target=body.passengers_target)
    limits = c.bookings.limits_for(ctx.info.booking_id)
    c.audit.record(
        "LIMITS_CHANGED",
        action=f"update limits ({ctx.info.label})",
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
    await c.bookings.stop_all()
    await c.provider.close()
    c.audit.record("SESSION_CLOSE", action="close browser, discard session")
    return {"session_ready": c.provider.session_ready}


# ------------------------------------------------------------------ simulation
def _mock(request: Request, booking_id: str | None) -> tuple[BookingContext, Any]:
    ctx = _ctx(request, booking_id)
    mock = _c(request).bookings.mock(ctx.info.booking_id)
    if mock is None:
        raise HTTPException(404, "Mock provider not active")
    return ctx, mock


@router.get("/mock/scenarios")
async def mock_scenarios(request: Request, booking_id: str | None = BookingQuery) -> dict[str, Any]:
    _, mock = _mock(request, booking_id)
    return {
        "current": mock.scenario_name,
        "scenarios": {name: s.description for name, s in mock.scenarios.items()},
    }


@router.post("/mock/scenario")
async def set_mock_scenario(
    body: ScenarioUpdate, request: Request, booking_id: str | None = BookingQuery
) -> dict[str, str]:
    ctx, _ = _mock(request, booking_id)
    try:
        _c(request).bookings.set_mock_scenario(ctx.info.booking_id, body.name)
    except KeyError as exc:
        raise HTTPException(404, "Unknown scenario") from exc
    _c(request).audit.record("MOCK_SCENARIO", action=body.name)
    return {"current": body.name}


@router.get("/mock/page", response_class=HTMLResponse)
async def mock_page(request: Request, booking_id: str | None = BookingQuery) -> HTMLResponse:
    """The simulated airline page, for demos. Mock mode only."""
    _, mock = _mock(request, booking_id)
    return HTMLResponse(render_mock_page(mock.current_page()))
