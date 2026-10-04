"""BrowserAgent - Playwright layer (AUTHENTICATION LAYER + page reading).

Principles:

* The user logs in **manually** in a visible, isolated, ephemeral browser
  context. The agent never types, stores or sees a password.
* CAPTCHAs / bot checks are detected and handed to the user, never bypassed.
* It only reads what is displayed and only clicks official buttons, and only
  when asked by the provider after an explicit human confirmation.
* Every selector comes from ``app.browser.selectors``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from app.browser.raw import PageKind, RawPageObservation, RawPassengerRow, RawUpgradeOffer
from app.browser.selectors.base import SelectorMap, SelectorSet
from app.config import Settings
from app.errors import (
    AgentTimeoutError,
    AuthenticationRequired,
    BookingNotFound,
    PageChanged,
    SelectorNotFound,
)

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Locator, Page, Playwright

logger = logging.getLogger(__name__)

_TEXT_TIMEOUT_MS = 2_000


@dataclass(frozen=True)
class ConfirmationScreen:
    total_text: str | None
    miles_text: str | None
    payment_form_present: bool
    final_button_present: bool


class BrowserAgent:
    def __init__(self, selectors: SelectorMap, settings: Settings) -> None:
        self.selectors = selectors
        self.settings = settings
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    # ------------------------------------------------------------- session
    @property
    def page(self) -> Page:
        if self._page is None:
            raise AuthenticationRequired("No browser session: call start_session() first")
        return self._page

    @property
    def is_open(self) -> bool:
        return self._page is not None

    async def start_session(self, headless: bool | None = None) -> None:
        """Launch an isolated browser. The context is ephemeral (incognito-like):
        cookies live only in memory and disappear on :meth:`close_session`."""
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        launch_kwargs: dict[str, object] = {
            "headless": self.settings.browser_headless if headless is None else headless
        }
        if self.settings.browser_executable_path:
            launch_kwargs["executable_path"] = self.settings.browser_executable_path
        self._browser = await self._playwright.chromium.launch(**launch_kwargs)  # type: ignore[arg-type]
        self._context = await self._browser.new_context(locale="fr-FR")
        self._page = await self._context.new_page()
        self._page.set_default_timeout(self.settings.navigation_timeout_ms)
        logger.info("Isolated browser session started (selectors=%s)", self.selectors.name)

    async def close_session(self) -> None:
        for closer in (self._context, self._browser):
            if closer is not None:
                try:
                    await closer.close()
                except Exception:  # pragma: no cover - best effort cleanup
                    logger.warning("Error while closing browser resources")
        if self._playwright is not None:
            await self._playwright.stop()
        self._page = self._context = self._browser = self._playwright = None
        logger.info("Browser session closed, session data discarded")

    async def open_air_france(self, url: str | None = None) -> None:
        target = url or self.settings.airline_base_url
        try:
            await self.page.goto(target, wait_until="domcontentloaded")
        except Exception as exc:
            raise AgentTimeoutError("Could not open the airline page") from exc

    def current_host(self) -> str:
        return urlparse(self.page.url).hostname or ""

    def on_official_host(self) -> bool:
        host = self.current_host()
        return any(host == h or host.endswith("." + h) for h in self.selectors.official_hosts)

    # ------------------------------------------------------------- locating
    async def _first(
        self, selector_set: SelectorSet, root: Page | Locator | None = None
    ) -> Locator | None:
        scope = root if root is not None else self.page
        for candidate in selector_set.candidates:
            try:
                locator = scope.locator(candidate).first
                if await locator.count() > 0:
                    return locator
            except Exception:  # invalid selector for this engine: try the fallback
                logger.debug("Selector candidate failed")
                continue
        return None

    async def _text(
        self, selector_set: SelectorSet, root: Page | Locator | None = None
    ) -> str | None:
        locator = await self._first(selector_set, root)
        if locator is None:
            return None
        try:
            text = await locator.inner_text(timeout=_TEXT_TIMEOUT_MS)
        except Exception:
            return None
        text = " ".join(text.split())
        return text or None

    async def _visible(self, selector_set: SelectorSet) -> bool:
        locator = await self._first(selector_set)
        if locator is None:
            return False
        try:
            return await locator.is_visible()
        except Exception:
            return False

    # ------------------------------------------------------------- auth
    async def detect_page_kind(self) -> PageKind:
        markers = self.selectors.page_markers
        # Order matters: a bot check or login wall wins over anything else.
        for kind in (PageKind.CAPTCHA, PageKind.LOGIN, PageKind.NOT_FOUND, PageKind.BOOKING):
            marker = markers.get(kind)
            if marker is not None and await self._visible(marker):
                return kind
        return PageKind.UNKNOWN

    async def is_logged_in(self) -> bool:
        return await self._visible(self.selectors.logged_in_marker)

    async def wait_for_manual_login(
        self, timeout_seconds: int | None = None, poll: float = 2.0
    ) -> None:
        """Wait while the USER logs in (and solves any bot check) by hand."""
        deadline = time.monotonic() + (
            timeout_seconds or self.settings.manual_login_timeout_seconds
        )
        announced_captcha = False
        while time.monotonic() < deadline:
            if await self.is_logged_in():
                logger.info("Manual login detected")
                return
            if not announced_captcha and await self.detect_page_kind() is PageKind.CAPTCHA:
                logger.warning("Bot check displayed: waiting for the user to solve it")
                announced_captcha = True
            await asyncio.sleep(poll)
        raise AuthenticationRequired("Manual login not completed in time")

    async def navigate_to_booking(self, booking_hint: str | None = None) -> None:
        """Go to the booking page through visible links only (no URL forging)."""
        if await self.detect_page_kind() is PageKind.BOOKING:
            return
        link = await self._first(self.selectors.booking_link)
        if link is None:
            raise BookingNotFound("Booking link not visible: open the booking manually")
        if booking_hint:
            filtered = self.page.locator(self.selectors.booking_link.candidates[0]).filter(
                has_text=re.compile(re.escape(booking_hint), re.IGNORECASE)
            )
            if await filtered.count() > 0:
                link = filtered.first
        await link.click()
        await self.page.wait_for_load_state("domcontentloaded")
        if await self.detect_page_kind() is not PageKind.BOOKING:
            raise BookingNotFound("Booking page not reached")

    # ------------------------------------------------------------- reading
    async def read_booking(self) -> dict[str, str | None]:
        values: dict[str, str | None] = {}
        for field_name, selector_set in self.selectors.fields.items():
            values[field_name] = await self._text(selector_set)
            if values[field_name] is None and selector_set.required:
                raise SelectorNotFound(field_name)
        return values

    async def read_passengers(self) -> list[RawPassengerRow]:
        rows: list[RawPassengerRow] = []
        for candidate in self.selectors.passenger_row.candidates:
            locators = await self.page.locator(candidate).all()
            if not locators:
                continue
            for row in locators:
                data = {
                    key: await self._text(selector_set, row)
                    for key, selector_set in self.selectors.passenger_fields.items()
                }
                rows.append(RawPassengerRow(**data))
            break
        return rows

    async def read_cabin(self) -> str | None:
        return await self._text(self.selectors.fields["cabin_text"])

    async def read_seats(self) -> str | None:
        return await self._text(self.selectors.fields["business_seats_text"])

    async def read_business_availability(self) -> str | None:
        return await self._text(self.selectors.fields["business_availability_text"])

    async def read_checkin_status(self) -> str | None:
        return await self._text(self.selectors.fields["checkin_text"])

    async def read_upgrade_options(self) -> list[RawUpgradeOffer]:
        offers: list[RawUpgradeOffer] = []
        for candidate in self.selectors.offer_row.candidates:
            locators = await self.page.locator(candidate).all()
            if not locators:
                continue
            for index, row in enumerate(locators, start=1):
                offer_id = (
                    await row.get_attribute(self.selectors.offer_id_attribute) or f"OFFER-{index}"
                )
                data = {
                    key: await self._text(selector_set, row)
                    for key, selector_set in self.selectors.offer_fields.items()
                }
                button = await self._first(self.selectors.offer_accept_button, row)
                has_button = button is not None and await button.is_visible()
                offers.append(
                    RawUpgradeOffer(offer_id=offer_id, has_accept_button=has_button, **data)
                )
            break
        return offers

    async def read_messages(self) -> list[str]:
        for candidate in self.selectors.messages.candidates:
            texts = await self.page.locator(candidate).all_inner_texts()
            if texts:
                return [" ".join(t.split()) for t in texts if t.strip()][:20]
        return []

    async def read_page(self) -> RawPageObservation:
        kind = await self.detect_page_kind()
        if kind is not PageKind.BOOKING:
            return RawPageObservation(page_kind=kind, messages=await self.read_messages())
        try:
            booking = await self.read_booking()
        except SelectorNotFound as exc:
            raise PageChanged(f"Required element missing: {exc.key}") from exc
        return RawPageObservation(
            page_kind=kind,
            passenger_rows=await self.read_passengers(),
            upgrade_offers=await self.read_upgrade_options(),
            messages=await self.read_messages(),
            **booking,
        )

    # ------------------------------------------------------------- acting
    async def click_offer(self, offer_id: str) -> None:
        for candidate in self.selectors.offer_row.candidates:
            row = self.page.locator(
                f"{candidate}[{self.selectors.offer_id_attribute}='{offer_id}']"
            ).first
            if await row.count() > 0:
                button = await self._first(self.selectors.offer_accept_button, row)
                if button is None:
                    raise SelectorNotFound("offer_accept_button")
                await button.click()
                return
        raise SelectorNotFound("offer_row")

    async def read_confirmation_screen(self) -> ConfirmationScreen:
        return ConfirmationScreen(
            total_text=await self._text(self.selectors.confirmation_total),
            miles_text=await self._text(self.selectors.confirmation_miles),
            payment_form_present=await self._visible(self.selectors.payment_form_marker),
            final_button_present=await self._visible(self.selectors.final_confirm_button),
        )

    async def click_final_confirm(self) -> None:
        button = await self._first(self.selectors.final_confirm_button)
        if button is None:
            raise SelectorNotFound("final_confirm_button")
        await button.click()
        await self.page.wait_for_load_state("domcontentloaded")

    # ------------------------------------------------------------- debug
    async def take_debug_screenshot(self, label: str) -> Path | None:
        """Only with DEBUG_MODE=true. PII elements are masked; file is owner-only.
        Screenshots are sensitive data and are never sent to the LLM."""
        if not self.settings.debug_mode or self._page is None:
            return None
        directory = Path(self.settings.screenshot_dir)
        directory.mkdir(parents=True, exist_ok=True)
        safe_label = re.sub(r"[^a-z0-9_-]", "", label.lower())[:40] or "debug"
        path = directory / f"{int(time.time())}_{safe_label}.png"
        masks = [self.page.locator(s) for s in self.selectors.pii_mask]
        await self.page.screenshot(path=str(path), mask=masks, full_page=True)
        os.chmod(path, 0o600)
        return path


def purge_old_screenshots(directory: Path, max_age_hours: int) -> int:
    """Retention policy: delete debug screenshots older than ``max_age_hours``."""
    if not directory.exists():
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for file in directory.glob("*.png"):
        if file.stat().st_mtime < cutoff:
            file.unlink(missing_ok=True)
            removed += 1
    return removed
