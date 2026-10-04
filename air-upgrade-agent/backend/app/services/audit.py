"""Audit trail: timestamp, event_type, decision, action, result - all anonymised."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select

from app.security.privacy import redact_sensitive_data
from app.services.db import AuditEventRow, Database

logger = logging.getLogger("audit")

#: Never recorded, even redacted: the key is dropped entirely.
FORBIDDEN_KEYS = {
    "password",
    "token",
    "cookie",
    "cookies",
    "credit_card",
    "card_number",
    "full_pnr",
    "pnr",
    "booking_reference",
    "full_ticket_number",
    "ticket_number",
    "storage_state",
    "authorization",
    "api_key",
}


class AuditEvent(BaseModel):
    id: int
    timestamp: datetime
    event_type: str
    decision: str | None
    action: str | None
    result: str | None
    details: dict[str, Any]


def _strip_forbidden(data: Any) -> Any:
    if isinstance(data, dict):
        return {
            k: _strip_forbidden(v) for k, v in data.items() if str(k).lower() not in FORBIDDEN_KEYS
        }
    if isinstance(data, list):
        return [_strip_forbidden(v) for v in data]
    return data


class AuditLog:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record(
        self,
        event_type: str,
        *,
        decision: str | None = None,
        action: str | None = None,
        result: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> AuditEvent:
        clean_details = redact_sensitive_data(_strip_forbidden(details or {}))
        row = AuditEventRow(
            event_type=event_type,
            decision=decision,
            action=redact_sensitive_data(action) if action else None,
            result=redact_sensitive_data(result) if result else None,
            details=clean_details,
        )
        with self.db.session() as session:
            session.add(row)
            session.commit()
            session.refresh(row)
        logger.info(
            "%s decision=%s action=%s result=%s", event_type, decision, row.action, row.result
        )
        return AuditEvent.model_validate(row, from_attributes=True)

    def recent(self, limit: int = 50) -> list[AuditEvent]:
        with self.db.session() as session:
            rows = session.scalars(
                select(AuditEventRow).order_by(AuditEventRow.id.desc()).limit(limit)
            ).all()
            return [AuditEvent.model_validate(r, from_attributes=True) for r in rows]
