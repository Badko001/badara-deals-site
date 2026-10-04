"""Builders for fictitious snapshots (no real personal data anywhere)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.models import (
    BookingSnapshot,
    Cabin,
    CheckinStatus,
    Eligibility,
    Flight,
    Observed,
    PageState,
    Passenger,
    SnapshotSource,
    UpgradeOption,
)

TEST_FLIGHT = Flight(
    airline="AF",
    flight_number="AF719",
    origin="DSS",
    destination="CDG",
    departure_datetime=datetime(2026, 10, 5, 23, 55, tzinfo=UTC),
)


def make_passengers(n: int = 3, eligible: int | None = None) -> list[Passenger]:
    eligible = n if eligible is None else eligible
    return [
        Passenger(
            internal_id=f"int-{i}",
            anonymized_id=f"PASSENGER_{i:03d}",
            current_cabin=Observed[Cabin].seen(Cabin.ECONOMY),
            current_seat=Observed[str].seen(f"3{i}A"),
            eligibility_status=Observed[Eligibility].seen(
                Eligibility.ELIGIBLE if i <= eligible else Eligibility.NOT_ELIGIBLE
            ),
        )
        for i in range(1, n + 1)
    ]


def make_option(
    *,
    cash: Decimal | int | None = 0,
    miles: int | None = 0,
    covers: int | None = 3,
    option_id: str = "OPT-1",
    available: bool | None = True,
    mixed_cash: Decimal | None = None,
) -> UpgradeOption:
    return UpgradeOption(
        option_id=option_id,
        cabin=Cabin.BUSINESS,
        cash_price=None if cash is None else Decimal(cash),
        currency="EUR",
        miles_price=miles,
        miles_cash_price=mixed_cash,
        passengers_covered=covers,
        availability=available,
        actionable=True,
        source=SnapshotSource.MOCK_AIR_FRANCE,
    )


def make_snapshot(
    *,
    business_seats: int | None = 3,
    business_available: bool | None = True,
    options: list[UpgradeOption] | None = None,
    passengers: list[Passenger] | None = None,
    passengers_count: int | None = 3,
    confirmed: bool = True,
    source: SnapshotSource = SnapshotSource.MOCK_AIR_FRANCE,
    checkin: CheckinStatus | None = CheckinStatus.OPEN,
    page_state: PageState = PageState.BOOKING_VISIBLE,
) -> BookingSnapshot:
    return BookingSnapshot(
        page_state=page_state,
        anonymized_booking_id="PNR_****123",
        flight=TEST_FLIGHT,
        passengers_count=(
            Observed[int].unknown()
            if passengers_count is None
            else Observed[int].seen(passengers_count)
        ),
        passengers=make_passengers() if passengers is None else passengers,
        current_cabin=Observed[Cabin].seen(Cabin.ECONOMY),
        business_available=(
            Observed[bool].unknown()
            if business_available is None
            else Observed[bool].seen(business_available)
        ),
        business_seats_visible=(
            Observed[int].unknown()
            if business_seats is None
            else Observed[int].seen(business_seats)
        ),
        upgrade_options=[make_option()] if options is None else options,
        checkin_status=(
            Observed[CheckinStatus].unknown()
            if checkin is None
            else Observed[CheckinStatus].seen(checkin)
        ),
        source=source,
        confirmed_by_airline=confirmed,
    )
