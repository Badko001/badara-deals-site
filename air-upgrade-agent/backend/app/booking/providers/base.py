"""AirlineProvider: the extension point for adding airlines (KLM, Brussels, Lufthansa...).

A provider only exposes what the airline *officially* offers in its UI to the
user who is legitimately logged in. It never calls private / undocumented APIs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.booking.observation import ObservationEngine
from app.browser.raw import RawPageObservation
from app.errors import HumanConfirmationRequired
from app.models import (
    Booking,
    BookingSnapshot,
    Cabin,
    CheckinStatus,
    Observed,
    SnapshotSource,
    UpgradeOption,
)
from app.models.actions import HumanConfirmation, ProviderActionResult


class AirlineProvider(ABC):
    name: str = "abstract"
    source: SnapshotSource
    #: Real airline sites must not be polled faster than the minimum interval.
    enforce_rate_limit: bool = True

    def __init__(self, observation: ObservationEngine | None = None) -> None:
        self.observation = observation or ObservationEngine()

    # ------------------------------------------------------------ lifecycle
    async def start(self) -> None:  # noqa: B027 - optional hook
        """Open the session (for real airlines: the user logs in manually)."""

    async def close(self) -> None:  # noqa: B027 - optional hook
        """Close the session and wipe temporary session data."""

    @property
    def session_ready(self) -> bool:
        return True

    # ------------------------------------------------------------ reading
    @abstractmethod
    async def read_raw(self) -> RawPageObservation:
        """Read the official booking page as-is."""

    @abstractmethod
    def is_confirmed_by_airline(self) -> bool:
        """Whether what was read comes from the airline's own system."""

    async def take_snapshot(self) -> BookingSnapshot:
        raw = await self.read_raw()
        return self.observation.build_snapshot(
            raw, source=self.source, confirmed_by_airline=self.is_confirmed_by_airline()
        )

    async def get_booking(self) -> Booking | None:
        snap = await self.take_snapshot()
        if snap.flight is None or snap.anonymized_booking_id is None:
            return None
        return Booking(
            anonymized_booking_id=snap.anonymized_booking_id,
            flight=snap.flight,
            passengers=snap.passengers,
            current_cabin=snap.current_cabin,
            checkin_status=snap.checkin_status,
        )

    async def get_upgrade_options(self) -> list[UpgradeOption]:
        return list((await self.take_snapshot()).upgrade_options)

    async def get_cabin_availability(self) -> dict[Cabin, Observed[int]]:
        snap = await self.take_snapshot()
        return {Cabin.BUSINESS: snap.business_seats_visible}

    async def get_checkin_status(self) -> Observed[CheckinStatus]:
        return (await self.take_snapshot()).checkin_status

    # ------------------------------------------------------------ acting
    async def request_upgrade(
        self, option: UpgradeOption, confirmation: HumanConfirmation | None
    ) -> ProviderActionResult:
        """Accept an *official* offer through the airline UI. Requires a human confirmation."""
        if not isinstance(confirmation, HumanConfirmation) or not confirmation.is_valid():
            raise HumanConfirmationRequired("A valid explicit human confirmation is required")
        if confirmation.option_id != option.option_id:
            raise HumanConfirmationRequired("Confirmation does not match this offer")
        return await self._accept_official_offer(option, confirmation)

    @abstractmethod
    async def _accept_official_offer(
        self, option: UpgradeOption, confirmation: HumanConfirmation
    ) -> ProviderActionResult:
        """Click the airline's own accept button. Never bypass payments or checks."""
