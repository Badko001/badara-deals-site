"""Human-in-the-loop confirmations: one pending request per opportunity, single use, expiring."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select

from app.errors import HumanConfirmationRequired
from app.models import BookingSnapshot, UpgradeDecision
from app.models.actions import HumanConfirmation
from app.models.domain import Money, utcnow
from app.services.db import ConfirmationRow, Database


class ConfirmationState(StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    EXECUTED = "EXECUTED"


class PendingConfirmation(BaseModel):
    confirmation_id: str
    option_id: str
    snapshot_id: str
    state: ConfirmationState
    max_cash: Money
    max_miles: int
    passengers: int
    created_at: datetime
    expires_at: datetime
    summary: dict[str, Any]


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _to_model(row: ConfirmationRow) -> PendingConfirmation:
    return PendingConfirmation(
        confirmation_id=row.confirmation_id,
        option_id=row.option_id,
        snapshot_id=row.snapshot_id,
        state=ConfirmationState(row.state),
        max_cash=Decimal(row.max_cash),
        max_miles=row.max_miles,
        passengers=row.passengers,
        created_at=_aware(row.created_at),
        expires_at=_aware(row.expires_at),
        summary=row.summary,
    )


class ConfirmationService:
    def __init__(self, db: Database, ttl_seconds: int) -> None:
        self.db = db
        self.ttl = timedelta(seconds=ttl_seconds)

    def create_pending(
        self, decision: UpgradeDecision, snapshot: BookingSnapshot
    ) -> PendingConfirmation:
        if decision.option_id is None or decision.cash_cost is None or decision.miles_cost is None:
            raise ValueError("Only a priced opportunity can be submitted for confirmation")
        flight = snapshot.flight
        now = utcnow()
        with self.db.session() as session:
            for row in session.scalars(
                select(ConfirmationRow).where(ConfirmationRow.state == ConfirmationState.PENDING)
            ):
                row.state = ConfirmationState.SUPERSEDED
            row = ConfirmationRow(
                confirmation_id=uuid.uuid4().hex,
                option_id=decision.option_id,
                snapshot_id=snapshot.snapshot_id,
                state=ConfirmationState.PENDING,
                max_cash=str(decision.cash_cost),
                max_miles=decision.miles_cost,
                passengers=decision.passengers_target,
                created_at=now,
                expires_at=now + self.ttl,
                summary={
                    "flight": flight.flight_number if flight else None,
                    "origin": flight.origin if flight else None,
                    "destination": flight.destination if flight else None,
                    "from_cabin": "ECONOMY",
                    "to_cabin": "BUSINESS",
                },
            )
            session.add(row)
            session.commit()
            return _to_model(row)

    def current_pending(self) -> PendingConfirmation | None:
        now = utcnow()
        with self.db.session() as session:
            rows = session.scalars(
                select(ConfirmationRow)
                .where(ConfirmationRow.state == ConfirmationState.PENDING)
                .order_by(ConfirmationRow.created_at.desc())
            ).all()
            for row in rows:
                if _aware(row.expires_at) <= now:
                    row.state = ConfirmationState.EXPIRED
                    continue
                session.commit()
                return _to_model(row)
            session.commit()
        return None

    def _transition(self, confirmation_id: str, new_state: ConfirmationState) -> ConfirmationRow:
        with self.db.session() as session:
            row = session.get(ConfirmationRow, confirmation_id)
            if row is None or row.state != ConfirmationState.PENDING:
                raise HumanConfirmationRequired("No pending confirmation with this id")
            if _aware(row.expires_at) <= utcnow():
                row.state = ConfirmationState.EXPIRED
                session.commit()
                raise HumanConfirmationRequired("Confirmation request expired")
            row.state = new_state
            row.decided_at = utcnow()
            session.commit()
            return row

    def decline(self, confirmation_id: str) -> None:
        """REFUSER: nothing else happens."""
        self._transition(confirmation_id, ConfirmationState.DECLINED)

    def confirm(self, confirmation_id: str) -> HumanConfirmation:
        """CONFIRMER: the only way to obtain a HumanConfirmation (single use)."""
        row = self._transition(confirmation_id, ConfirmationState.CONFIRMED)
        return HumanConfirmation(
            confirmation_id=row.confirmation_id,
            option_id=row.option_id,
            snapshot_id=row.snapshot_id,
            max_cash=Decimal(row.max_cash),
            max_miles=row.max_miles,
            passengers=row.passengers,
            confirmed_at=_aware(row.decided_at or utcnow()),
            expires_at=_aware(row.expires_at),
        )

    def mark_executed(self, confirmation_id: str) -> None:
        with self.db.session() as session:
            row = session.get(ConfirmationRow, confirmation_id)
            if row is not None:
                row.state = ConfirmationState.EXECUTED
                session.commit()

    def expire_all(self) -> int:
        with self.db.session() as session:
            rows = session.scalars(
                select(ConfirmationRow).where(ConfirmationRow.state == ConfirmationState.PENDING)
            ).all()
            for row in rows:
                row.state = ConfirmationState.EXPIRED
            session.commit()
            return len(rows)
