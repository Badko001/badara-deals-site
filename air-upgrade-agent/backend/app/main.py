"""FastAPI entry point: ``uvicorn app.main:app``."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.browser.agent import purge_old_screenshots
from app.config import Settings, get_settings
from app.errors import (
    AirUpgradeError,
    AuthenticationRequired,
    HumanConfirmationRequired,
    HumanVerificationRequired,
)
from app.monitoring.engine import RateLimited
from app.security.logging import configure_logging
from app.security.privacy import get_privacy_manager
from app.services.container import Container

logger = logging.getLogger(__name__)

_STATUS = {
    HumanConfirmationRequired: 409,
    RateLimited: 429,
    AuthenticationRequired: 428,
    HumanVerificationRequired: 428,
}


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(logging.DEBUG if settings.debug_mode else logging.INFO)
    if settings.database_url.startswith("sqlite:///"):
        Path(settings.database_url.removeprefix("sqlite:///")).parent.mkdir(
            parents=True, exist_ok=True
        )
    container = container or Container.build(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        purge_old_screenshots(Path(settings.screenshot_dir), settings.screenshot_retention_hours)
        logger.info(
            "AIR UPGRADE AGENT started (provider=%s, dry_run=%s)",
            container.provider.name,
            settings.dry_run,
        )
        yield
        await container.monitoring.stop_monitoring()
        await container.provider.close()

    app = FastAPI(title="AIR UPGRADE AGENT", version="0.1.0", lifespan=lifespan)
    app.state.container = container
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(AirUpgradeError)
    async def domain_error(_: Request, exc: AirUpgradeError) -> JSONResponse:
        status = next((code for cls, code in _STATUS.items() if isinstance(exc, cls)), 502)
        message = get_privacy_manager().sanitize_text(str(exc))
        return JSONResponse(
            status_code=status, content={"error": type(exc).__name__, "message": message}
        )

    app.include_router(router)
    return app


app = create_app()
