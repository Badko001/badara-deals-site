"""Price watch API: watches, checks, history, alerts."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.pricewatch.engine import CheckResult, PriceWatchEngine
from app.pricewatch.models import FareQuote, PriceAlert, PriceWatch, WatchSummary

router = APIRouter(prefix="/api/pricewatch", tags=["pricewatch"])


def _engine(request: Request) -> PriceWatchEngine:
    engine: PriceWatchEngine = request.app.state.container.pricewatch
    return engine


@router.get("/status")
async def status(request: Request) -> dict[str, Any]:
    engine = _engine(request)
    return {
        "source": engine.provider.name,
        "running": engine.running,
        "last_run": engine.last_run,
        "next_run": engine.next_run,
        "interval_seconds": engine.settings.price_watch_interval_seconds,
    }


@router.get("/watches", response_model=list[WatchSummary])
async def list_watches(request: Request) -> list[WatchSummary]:
    return _engine(request).summaries()


@router.post("/watches", response_model=PriceWatch, status_code=201)
async def add_watch(watch: PriceWatch, request: Request) -> PriceWatch:
    return _engine(request).add_watch(watch)


@router.put("/watches/{watch_id}", response_model=PriceWatch)
async def update_watch(watch_id: str, watch: PriceWatch, request: Request) -> PriceWatch:
    try:
        return _engine(request).update_watch(watch.model_copy(update={"watch_id": watch_id}))
    except KeyError as exc:
        raise HTTPException(404, "Unknown watch") from exc


@router.delete("/watches/{watch_id}")
async def delete_watch(watch_id: str, request: Request) -> dict[str, bool]:
    if not _engine(request).delete_watch(watch_id):
        raise HTTPException(404, "Unknown watch")
    return {"deleted": True}


@router.post("/watches/{watch_id}/check", response_model=CheckResult)
async def check_watch(watch_id: str, request: Request) -> CheckResult:
    try:
        return await _engine(request).check_watch(watch_id)
    except KeyError as exc:
        raise HTTPException(404, "Unknown watch") from exc


@router.get("/watches/{watch_id}/history", response_model=list[FareQuote])
async def history(watch_id: str, request: Request) -> list[FareQuote]:
    return _engine(request).history(watch_id)


@router.get("/alerts", response_model=list[PriceAlert])
async def alerts(request: Request) -> list[PriceAlert]:
    return _engine(request).recent_alerts()


@router.post("/start")
async def start(request: Request) -> dict[str, bool]:
    await _engine(request).start()
    return {"running": True}


@router.post("/stop")
async def stop(request: Request) -> dict[str, bool]:
    await _engine(request).stop()
    return {"running": False}
