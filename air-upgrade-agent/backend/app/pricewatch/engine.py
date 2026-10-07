"""PriceWatchEngine: polite periodic checks of published fares + alerts.

* Each check runs at most ``max_dates_per_watch`` searches per watch, rotating
  through the (destination x date) combinations, so the source is never hammered.
* Alerts: below the user's threshold, a new lowest price, or a clear drop.
  The same destination is never re-alerted unless the price goes lower again.
* No booking, no payment: an alert links to the official airline website.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import func, select

from app.config import Settings
from app.models.domain import utcnow
from app.notifications.service import NotificationEvent, NotificationService
from app.pricewatch.models import (
    AlertKind,
    FareCabin,
    FareQuote,
    PriceAlert,
    PriceWatch,
    WatchSummary,
)
from app.pricewatch.providers import FareProvider, FareSourceError
from app.services.audit import AuditLog
from app.services.db import Database, FareQuoteRow, PriceAlertRow, PriceWatchRow

logger = logging.getLogger(__name__)

#: Official websites only - the user books and pays there.
OFFICIAL_BOOKING_SITES = {
    "AF": "https://wwws.airfrance.fr/",
    "KL": "https://www.klm.fr/",
    "TO": "https://www.transavia.com/fr-FR/accueil/",
}
NEW_LOW_MIN_HISTORY = 3
NEW_LOW_MARGIN = Decimal("0.03")

_KIND_TEXT = {
    AlertKind.BELOW_THRESHOLD: "sous votre prix maximum",
    AlertKind.NEW_LOW: "prix le plus bas observé",
    AlertKind.PRICE_DROP: "baisse de prix",
}


class CheckResult(BaseModel):
    watch_id: str
    searches: int
    quotes: list[FareQuote]
    alerts: list[PriceAlert]
    errors: list[str]


def default_watches(today: date) -> list[PriceWatch]:
    """Starting points requested by the user - all editable from the dashboard."""
    return [
        PriceWatch(
            name="Dakar ↔ Paris",
            origin="DSS",
            destinations=["CDG"],
            depart_from=today + timedelta(days=14),
            depart_to=today + timedelta(days=120),
            trip_length_days=14,
            passengers=1,
            airlines=["AF"],
        ),
        PriceWatch(
            name="Escapades Europe",
            origin="CDG",
            destinations=["LIS", "BCN", "FCO", "AMS", "ATH", "MAD", "PRG", "OPO"],
            depart_from=today + timedelta(days=7),
            depart_to=today + timedelta(days=60),
            trip_length_days=3,
            passengers=1,
            max_total_price=Decimal(150),
            airlines=["AF", "KL", "TO"],
        ),
    ]


class PriceWatchEngine:
    def __init__(
        self,
        *,
        provider: FareProvider,
        db: Database,
        notifier: NotificationService,
        audit: AuditLog,
        settings: Settings,
    ) -> None:
        self.provider = provider
        self.db = db
        self.notifier = notifier
        self.audit = audit
        self.settings = settings
        self.running = False
        self.last_run: datetime | None = None
        self.next_run: datetime | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------ watches CRUD
    def add_watch(self, watch: PriceWatch) -> PriceWatch:
        with self.db.session() as session:
            session.add(
                PriceWatchRow(
                    watch_id=watch.watch_id, data=watch.model_dump(mode="json"), active=watch.active
                )
            )
            session.commit()
        self.audit.record("WATCH_ADDED", action=f"{watch.origin}->{','.join(watch.destinations)}")
        return watch

    def list_watches(self) -> list[PriceWatch]:
        with self.db.session() as session:
            rows = session.scalars(select(PriceWatchRow).order_by(PriceWatchRow.created_at)).all()
            return [PriceWatch.model_validate({**r.data, "active": r.active}) for r in rows]

    def get_watch(self, watch_id: str) -> PriceWatch | None:
        with self.db.session() as session:
            row = session.get(PriceWatchRow, watch_id)
            return PriceWatch.model_validate({**row.data, "active": row.active}) if row else None

    def update_watch(self, watch: PriceWatch) -> PriceWatch:
        with self.db.session() as session:
            row = session.get(PriceWatchRow, watch.watch_id)
            if row is None:
                raise KeyError(watch.watch_id)
            row.data = watch.model_dump(mode="json")
            row.active = watch.active
            row.cursor = 0
            session.commit()
        return watch

    def delete_watch(self, watch_id: str) -> bool:
        with self.db.session() as session:
            row = session.get(PriceWatchRow, watch_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
        self.audit.record("WATCH_DELETED", action=watch_id)
        return True

    def seed_defaults(self, today: date | None = None) -> None:
        if not self.list_watches():
            for watch in default_watches(today or date.today()):
                self.add_watch(watch)

    # ------------------------------------------------------------ checks
    def _combinations(self, watch: PriceWatch, today: date | None) -> list[tuple[str, date]]:
        dates = watch.sample_dates(self.settings.max_dates_per_watch, today)
        return [(dest, d) for dest in watch.destinations for d in dates]

    def _next_batch(self, watch: PriceWatch, today: date | None) -> list[tuple[str, date]]:
        combos = self._combinations(watch, today)
        if not combos:
            return []
        size = min(self.settings.max_dates_per_watch, len(combos))
        with self.db.session() as session:
            row = session.get(PriceWatchRow, watch.watch_id)
            start = (row.cursor if row else 0) % len(combos)
            if row is not None:
                row.cursor = (start + size) % len(combos)
                session.commit()
        return [combos[(start + i) % len(combos)] for i in range(size)]

    async def check_watch(self, watch_id: str, today: date | None = None) -> CheckResult:
        watch = self.get_watch(watch_id)
        if watch is None:
            raise KeyError(watch_id)
        async with self._lock:
            batch = self._next_batch(watch, today)
            quotes: list[FareQuote] = []
            errors: list[str] = []
            for destination, depart in batch:
                ret = (
                    depart + timedelta(days=watch.trip_length_days)
                    if watch.trip_length_days
                    else None
                )
                try:
                    found = await self.provider.search(
                        origin=watch.origin,
                        destination=destination,
                        depart_date=depart,
                        return_date=ret,
                        passengers=watch.passengers,
                        cabin=watch.cabin,
                    )
                except FareSourceError as exc:
                    errors.append(str(exc))
                    if "rate limit" in str(exc):
                        break  # stop politely; next check continues the rotation
                    continue
                allowed = [
                    q for q in found if not watch.airlines or (q.carrier or "") in watch.airlines
                ]
                if allowed:
                    quotes.append(min(allowed, key=lambda q: q.total_price))
            alerts = await self._process(watch, quotes)
            self.audit.record(
                "PRICE_CHECK",
                action=f"{watch.name}: {len(batch)} recherche(s)",
                result=f"{len(quotes)} tarif(s), {len(alerts)} alerte(s)",
                details={"errors": errors[:5], "source": self.provider.name},
            )
            return CheckResult(
                watch_id=watch_id, searches=len(batch), quotes=quotes, alerts=alerts, errors=errors
            )

    async def _process(self, watch: PriceWatch, quotes: list[FareQuote]) -> list[PriceAlert]:
        # Best quote per destination for this check.
        best: dict[str, FareQuote] = {}
        for q in quotes:
            if q.destination not in best or q.total_price < best[q.destination].total_price:
                best[q.destination] = q
        alerts: list[PriceAlert] = []
        with self.db.session() as session:
            for dest, quote in best.items():
                history = session.scalars(
                    select(FareQuoteRow).where(
                        FareQuoteRow.watch_id == watch.watch_id, FareQuoteRow.destination == dest
                    )
                ).all()
                prev_prices = [Decimal(r.total_price) for r in history]
                same_date = [
                    Decimal(r.total_price)
                    for r in history
                    if r.data.get("depart_date") == quote.depart_date.isoformat()
                ]
                last_alert = session.scalars(
                    select(PriceAlertRow)
                    .where(
                        PriceAlertRow.watch_id == watch.watch_id, PriceAlertRow.destination == dest
                    )
                    .order_by(PriceAlertRow.id.desc())
                    .limit(1)
                ).first()
                for q in quotes:
                    if q.destination == dest:
                        session.add(
                            FareQuoteRow(
                                watch_id=watch.watch_id,
                                destination=dest,
                                total_price=str(q.total_price),
                                data=q.model_dump(mode="json"),
                            )
                        )
                kind, previous = self._classify(watch, quote, prev_prices, same_date)
                if kind is None:
                    continue
                if last_alert is not None and quote.total_price >= Decimal(last_alert.total_price):
                    continue  # already alerted at this price or lower
                alert = self._build_alert(watch, kind, quote, previous)
                session.add(
                    PriceAlertRow(
                        watch_id=watch.watch_id,
                        destination=dest,
                        kind=kind.value,
                        total_price=str(quote.total_price),
                        data=alert.model_dump(mode="json"),
                    )
                )
                alerts.append(alert)
            session.commit()
        for alert in alerts:
            await self.notifier.notify(NotificationEvent.PRICE_ALERT, message=alert.message)
        return alerts

    def _classify(
        self,
        watch: PriceWatch,
        quote: FareQuote,
        prev_prices: list[Decimal],
        same_date: list[Decimal],
    ) -> tuple[AlertKind | None, Decimal | None]:
        price = quote.total_price
        if watch.max_total_price is not None and price <= watch.max_total_price:
            return AlertKind.BELOW_THRESHOLD, min(prev_prices) if prev_prices else None
        if len(prev_prices) >= NEW_LOW_MIN_HISTORY:
            low = min(prev_prices)
            if price < low * (1 - NEW_LOW_MARGIN):
                return AlertKind.NEW_LOW, low
        if same_date:
            last = same_date[-1]
            drop = Decimal(1) - self.settings.price_drop_alert_percent / Decimal(100)
            if price <= last * drop:
                return AlertKind.PRICE_DROP, last
        return None, None

    @staticmethod
    def _build_alert(
        watch: PriceWatch, kind: AlertKind, quote: FareQuote, previous: Decimal | None
    ) -> PriceAlert:
        url = OFFICIAL_BOOKING_SITES.get(quote.carrier or "")
        dates = f"{quote.depart_date:%d/%m}"
        if quote.return_date:
            dates += f" → {quote.return_date:%d/%m}"
        trip = "aller-retour" if quote.return_date else "aller simple"
        before = f" (avant : {previous:.0f} {quote.currency})" if previous else ""
        message = (
            f"✈ {watch.name} — {watch.origin} → {quote.destination}, {trip} {dates}\n"
            f"{quote.total_price:.0f} {quote.currency} pour {quote.passengers} passager(s) "
            f"({quote.price_per_passenger:.0f} {quote.currency}/pers.){before} : {_KIND_TEXT[kind]}.\n"
            + (
                f"Réservez sur le site officiel : {url}"
                if url
                else "Réservez sur le site officiel de la compagnie."
            )
        )
        return PriceAlert(
            watch_id=watch.watch_id,
            watch_name=watch.name,
            kind=kind,
            quote=quote,
            previous_price=previous,
            booking_url=url,
            message=message,
        )

    # ------------------------------------------------------------ reads
    def summaries(self) -> list[WatchSummary]:
        out: list[WatchSummary] = []
        with self.db.session() as session:
            for watch in self.list_watches():
                rows = session.scalars(
                    select(FareQuoteRow)
                    .where(FareQuoteRow.watch_id == watch.watch_id)
                    .order_by(FareQuoteRow.id)
                ).all()
                quotes = [FareQuote.model_validate(r.data) for r in rows]
                last_ts = rows[-1].timestamp if rows else None
                # Latest known price for each (destination, date), then the cheapest of them.
                latest: dict[tuple[str, date], FareQuote] = {}
                for q in quotes:
                    latest[(q.destination, q.depart_date)] = q
                current = list(latest.values())
                out.append(
                    WatchSummary(
                        watch=watch,
                        best_current=min(current, key=lambda q: q.total_price) if current else None,
                        lowest_ever=min(quotes, key=lambda q: q.total_price) if quotes else None,
                        last_check=last_ts,
                        quotes_count=len(quotes),
                    )
                )
        return out

    def history(self, watch_id: str, limit: int = 200) -> list[FareQuote]:
        with self.db.session() as session:
            rows = session.scalars(
                select(FareQuoteRow)
                .where(FareQuoteRow.watch_id == watch_id)
                .order_by(FareQuoteRow.id.desc())
                .limit(limit)
            ).all()
            return [FareQuote.model_validate(r.data) for r in rows]

    def recent_alerts(self, limit: int = 30) -> list[PriceAlert]:
        with self.db.session() as session:
            rows = session.scalars(
                select(PriceAlertRow).order_by(PriceAlertRow.id.desc()).limit(limit)
            ).all()
            return [PriceAlert.model_validate(r.data) for r in rows]

    def quotes_count(self) -> int:
        with self.db.session() as session:
            return int(session.scalar(select(func.count()).select_from(FareQuoteRow)) or 0)

    # ------------------------------------------------------------ loop
    async def check_all(self) -> list[CheckResult]:
        results = []
        for watch in self.list_watches():
            if watch.active:
                results.append(await self.check_watch(watch.watch_id))
        self.last_run = utcnow()
        return results

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self.running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        self.running = False
        self.next_run = None

    async def _run(self) -> None:
        interval = self.settings.price_watch_interval_seconds
        while not self._stop.is_set():
            try:
                await self.check_all()
            except Exception as exc:  # never crash the loop, never guess
                logger.warning("Price check failed: %s", type(exc).__name__)
            self.next_run = utcnow() + timedelta(seconds=interval)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=interval)


__all__ = ["CheckResult", "FareCabin", "PriceWatchEngine", "default_watches"]
