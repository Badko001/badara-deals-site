"""Persistence (SQLite for the MVP, PostgreSQL by changing DATABASE_URL).

Only already-redacted data is stored. No password, token, cookie, card number,
full PNR or full ticket number ever reaches these tables.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Text, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.domain import utcnow


class Base(DeclarativeBase):
    pass


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SnapshotRow(Base):
    __tablename__ = "snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    decision: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class ConfirmationRow(Base):
    __tablename__ = "confirmations"

    confirmation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    option_id: Mapped[str] = mapped_column(String(64))
    snapshot_id: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), index=True)
    max_cash: Mapped[str] = mapped_column(String(32))
    max_miles: Mapped[int] = mapped_column(Integer)
    passengers: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RuntimeSettingRow(Base):
    __tablename__ = "runtime_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(256))


class PriceWatchRow(Base):
    __tablename__ = "price_watches"

    watch_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(default=True)
    cursor: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FareQuoteRow(Base):
    __tablename__ = "fare_quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    watch_id: Mapped[str] = mapped_column(String(32), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    destination: Mapped[str] = mapped_column(String(3), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    total_price: Mapped[str] = mapped_column(String(32))


class PriceAlertRow(Base):
    __tablename__ = "price_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    watch_id: Mapped[str] = mapped_column(String(32), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    destination: Mapped[str] = mapped_column(String(3))
    kind: Mapped[str] = mapped_column(String(32))
    total_price: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class Database:
    def __init__(self, url: str) -> None:
        kwargs: dict[str, Any] = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if ":memory:" in url or url == "sqlite://":
                kwargs["poolclass"] = StaticPool
        self.engine: Engine = create_engine(url, **kwargs)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)

    def session(self) -> Session:
        return self._sessions()
