"""User-adjustable limits (cash / miles / passengers), persisted - no code change needed."""

from __future__ import annotations

from decimal import Decimal

from app.config import Settings
from app.models import CostLimits
from app.services.db import Database, RuntimeSettingRow


class RuntimeSettings:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def _get(self, key: str) -> str | None:
        with self.db.session() as session:
            row = session.get(RuntimeSettingRow, key)
            return row.value if row else None

    def get_limits(self) -> CostLimits:
        cash = self._get("cash_limit")
        miles = self._get("miles_limit")
        passengers = self._get("passengers_target")
        return CostLimits(
            cash_limit=Decimal(cash) if cash is not None else self.settings.cash_limit,
            miles_limit=int(miles) if miles is not None else self.settings.miles_limit,
            passengers_target=(
                int(passengers) if passengers is not None else self.settings.passengers_target
            ),
        )

    def set_limits(
        self, cash_limit: Decimal, miles_limit: int, passengers_target: int | None = None
    ) -> CostLimits:
        limits = CostLimits(
            cash_limit=cash_limit,
            miles_limit=miles_limit,
            passengers_target=(
                passengers_target
                if passengers_target is not None
                else self.get_limits().passengers_target
            ),
        )
        with self.db.session() as session:
            for key, value in (
                ("cash_limit", str(limits.cash_limit)),
                ("miles_limit", str(limits.miles_limit)),
                ("passengers_target", str(limits.passengers_target)),
            ):
                row = session.get(RuntimeSettingRow, key)
                if row is None:
                    session.add(RuntimeSettingRow(key=key, value=value))
                else:
                    row.value = value
            session.commit()
        return limits
