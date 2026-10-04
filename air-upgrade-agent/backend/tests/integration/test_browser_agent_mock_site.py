"""Real Playwright BrowserAgent against the local MOCK AIR FRANCE page (no real site)."""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.booking.providers.airfrance import AirFranceProvider
from app.booking.providers.mock_airfrance import MockAirFrance
from app.browser.mock_page import render_mock_page
from app.browser.selectors import AIR_FRANCE_SELECTORS, MOCK_AIR_FRANCE_SELECTORS
from app.config import Settings
from app.decision.engine import evaluate_upgrade
from app.errors import HumanConfirmationRequired, PageChanged
from app.models import Cabin, CostLimits, DecisionStatus
from app.models.actions import HumanConfirmation
from app.models.domain import utcnow

CHROMIUM = os.environ.get("BROWSER_EXECUTABLE_PATH", "/opt/pw-browsers/chromium")

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(
        os.environ.get("SKIP_BROWSER_TESTS") == "1", reason="browser tests disabled"
    ),
]


def _settings(tmp_path: Path, **kw: object) -> Settings:
    return Settings(
        browser_headless=True,
        browser_executable_path=CHROMIUM if Path(CHROMIUM).exists() else None,
        manual_login_timeout_seconds=10,
        screenshot_dir=tmp_path / "shots",
        **kw,  # type: ignore[arg-type]
    )


async def _provider(tmp_path: Path, scenario: str, **kw: object) -> AirFranceProvider:
    page = tmp_path / f"{scenario}.html"
    page.write_text(render_mock_page(MockAirFrance(scenario).current_page()), encoding="utf-8")
    provider = AirFranceProvider(
        _settings(tmp_path, **kw),
        selectors=MOCK_AIR_FRANCE_SELECTORS,
        start_url=page.as_uri(),
    )
    await provider.start()
    for _ in range(50):
        if provider.session_ready:
            break
        await asyncio.sleep(0.1)
    return provider


def _confirmation(option_id: str, snapshot_id: str) -> HumanConfirmation:
    now = utcnow()
    return HumanConfirmation(
        confirmation_id="c-1",
        option_id=option_id,
        snapshot_id=snapshot_id,
        max_cash=Decimal(0),
        max_miles=0,
        passengers=3,
        confirmed_at=now,
        expires_at=now + timedelta(minutes=5),
    )


async def test_browser_reads_mock_page_and_upgrades_after_confirmation(tmp_path: Path) -> None:
    provider = await _provider(tmp_path, "free_upgrade_3_business", debug_mode=True)
    try:
        assert provider.session_ready
        raw = await provider.agent.read_page()
        assert raw == MockAirFrance("free_upgrade_3_business").current_page()

        snapshot = await provider.take_snapshot()
        assert snapshot.confirmed_by_airline
        decision = evaluate_upgrade(snapshot, CostLimits())
        assert decision.status is DecisionStatus.OPPORTUNITY
        option = snapshot.upgrade_options[0]

        with pytest.raises(HumanConfirmationRequired):
            await provider.request_upgrade(option, None)

        result = await provider.request_upgrade(
            option, _confirmation(option.option_id, snapshot.snapshot_id)
        )
        assert result.submitted, result.message

        after = await provider.take_snapshot()
        assert all(p.current_cabin.value is Cabin.BUSINESS for p in after.passengers)

        shots = list((tmp_path / "shots").glob("*.png"))
        assert shots, "DEBUG_MODE=true should produce masked screenshots"
        assert all(oct(s.stat().st_mode)[-3:] == "600" for s in shots)
    finally:
        await provider.close()


async def test_paid_offer_stops_at_payment_form(tmp_path: Path) -> None:
    provider = await _provider(tmp_path, "paid_upgrade")
    try:
        snapshot = await provider.take_snapshot()
        option = snapshot.upgrade_options[0]
        result = await provider.request_upgrade(
            option, _confirmation(option.option_id, snapshot.snapshot_id)
        )
        assert not result.submitted
        after = await provider.take_snapshot()
        assert all(p.current_cabin.value is Cabin.ECONOMY for p in after.passengers)
        assert not list((tmp_path / "shots").glob("*.png")), "no screenshots when DEBUG_MODE=false"
    finally:
        await provider.close()


async def test_login_and_captcha_pages_are_detected(tmp_path: Path) -> None:
    for scenario, expected in (
        ("login_required", "AUTHENTICATION_REQUIRED"),
        ("captcha", "HUMAN_VERIFICATION_REQUIRED"),
    ):
        page = tmp_path / f"{scenario}.html"
        page.write_text(render_mock_page(MockAirFrance(scenario).current_page()), encoding="utf-8")
        provider = AirFranceProvider(
            _settings(tmp_path), selectors=MOCK_AIR_FRANCE_SELECTORS, start_url=page.as_uri()
        )
        await provider.agent.start_session()
        try:
            await provider.agent.open_air_france(page.as_uri())
            snapshot = await provider.take_snapshot()
            assert snapshot.page_state.value == expected
            assert not snapshot.confirmed_by_airline
        finally:
            await provider.close()


async def test_unverified_real_selectors_never_click(tmp_path: Path) -> None:
    provider = AirFranceProvider(_settings(tmp_path), selectors=AIR_FRANCE_SELECTORS)
    snapshot_option = MockAirFrance().current_page().upgrade_offers[0]
    from tests.fixtures.snapshots import make_option

    option = make_option(option_id=snapshot_option.offer_id)
    with pytest.raises(PageChanged):
        await provider.request_upgrade(option, _confirmation(option.option_id, "s"))
