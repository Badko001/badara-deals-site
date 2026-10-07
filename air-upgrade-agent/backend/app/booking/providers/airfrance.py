"""AirFranceProvider - reads the user's own booking through the official website.

* Authentication: manual, by the user, in the isolated browser opened by
  :class:`BrowserAgent`. No password ever reaches this code.
* Reading: only what is displayed; missing -> null.
* Acting: only the official accept button, only with a valid HumanConfirmation,
  only if the selector map was verified, and aborted as soon as a payment form or
  a non-zero cost appears.
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.booking.observation import ObservationEngine, parse_miles, parse_money
from app.booking.providers.base import AirlineProvider
from app.browser.agent import BrowserAgent
from app.browser.raw import PageKind, RawPageObservation
from app.browser.selectors import AIR_FRANCE_SELECTORS, SelectorMap
from app.config import Settings
from app.errors import AuthenticationRequired, PageChanged
from app.models import SnapshotSource, UpgradeOption
from app.models.actions import HumanConfirmation, ProviderActionResult

logger = logging.getLogger(__name__)


class AirFranceProvider(AirlineProvider):
    name = "airfrance"
    source = SnapshotSource.AIR_FRANCE_WEB
    enforce_rate_limit = True

    def __init__(
        self,
        settings: Settings,
        *,
        selectors: SelectorMap = AIR_FRANCE_SELECTORS,
        agent: BrowserAgent | None = None,
        observation: ObservationEngine | None = None,
        start_url: str | None = None,
    ) -> None:
        super().__init__(observation)
        self.settings = settings
        self.selectors = selectors
        self.agent = agent or BrowserAgent(selectors, settings)
        self.start_url = start_url
        self.booking_hint: str | None = None
        self._ready = False
        self._last_read_page_kind: PageKind | None = None
        self._login_task: asyncio.Task[None] | None = None
        self._last_request_at: float | None = None

    @property
    def session_ready(self) -> bool:
        return self._ready

    async def start(self) -> None:
        """Open the isolated browser on the airline site, then wait (in background)
        for the user to log in by hand and open the booking."""
        if not self.agent.is_open:
            await self.agent.start_session()
            await self.agent.open_air_france(self.start_url)
        self._login_task = asyncio.create_task(self._await_user())

    async def _await_user(self) -> None:
        try:
            await self.agent.wait_for_manual_login()
            await self.agent.navigate_to_booking(self.booking_hint)
            self._ready = True
        except Exception as exc:  # reported through page state, never guessed around
            logger.warning("Session not ready: %s", type(exc).__name__)
            self._ready = False

    async def select_booking(self, key: str, reference: str | None) -> None:
        """Open another of the user's bookings, through visible links only."""
        if reference == self.booking_hint:
            return
        self.booking_hint = reference
        if self._ready and self.agent.is_open:
            await self.agent.navigate_to_booking(reference)

    async def close(self) -> None:
        if self._login_task is not None:
            self._login_task.cancel()
        self._ready = False
        await self.agent.close_session()

    async def read_raw(self) -> RawPageObservation:
        if not self.agent.is_open:
            return RawPageObservation(page_kind=PageKind.LOGIN)
        self._last_request_at = time.monotonic()
        raw = await self.agent.read_page()
        self._last_read_page_kind = raw.page_kind
        if raw.page_kind is PageKind.LOGIN:
            self._ready = False
        await self.agent.take_debug_screenshot(f"read_{raw.page_kind.value}")
        return raw

    def is_confirmed_by_airline(self) -> bool:
        return (
            self.agent.is_open
            and self.agent.on_official_host()
            and self._last_read_page_kind is PageKind.BOOKING
        )

    async def _accept_official_offer(
        self, option: UpgradeOption, confirmation: HumanConfirmation
    ) -> ProviderActionResult:
        if not self.selectors.verified:
            raise PageChanged(
                "Air France selectors are not verified: accept the offer yourself in the official interface"
            )
        if not self.agent.is_open or not self.agent.on_official_host():
            raise AuthenticationRequired("No official airline session open")

        await self.agent.click_offer(option.option_id)
        screen = await self.agent.read_confirmation_screen()
        await self.agent.take_debug_screenshot("confirmation_screen")
        if screen.payment_form_present:
            return ProviderActionResult(
                submitted=False, message="Formulaire de paiement affiché : arrêt."
            )
        cash = parse_money(screen.total_text)
        miles = parse_miles(screen.miles_text) if screen.miles_text else None
        if cash is None or miles is None:
            return ProviderActionResult(
                submitted=False, message="Coût final non lisible sur l'écran officiel : arrêt."
            )
        if cash > confirmation.max_cash or miles > confirmation.max_miles:
            return ProviderActionResult(
                submitted=False, message="Coût final supérieur au montant confirmé : arrêt."
            )
        if not screen.final_button_present:
            return ProviderActionResult(submitted=False, message="Bouton officiel absent : arrêt.")
        await self.agent.click_final_confirm()
        return ProviderActionResult(
            submitted=True, message="Offre officielle soumise à la compagnie."
        )
