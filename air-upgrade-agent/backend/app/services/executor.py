"""UpgradeExecutor - the only path to a real action.

CONFIRM click -> single-use HumanConfirmation -> fresh re-read of the airline page ->
deterministic re-evaluation -> (DRY_RUN: stop here) -> official button ->
independent verification. Success is claimed only if the airline itself now
shows Business for every passenger.
"""

from __future__ import annotations

import logging

from app.booking.providers.base import AirlineProvider
from app.config import Settings
from app.decision.engine import evaluate_upgrade
from app.errors import AirUpgradeError
from app.models import Cabin, CostLimits, DecisionStatus
from app.models.actions import ExecutionStatus, HumanConfirmation, UpgradeExecutionResult
from app.services.audit import AuditLog
from app.services.confirmations import ConfirmationService

logger = logging.getLogger(__name__)


class UpgradeExecutor:
    def __init__(
        self,
        provider: AirlineProvider,
        confirmations: ConfirmationService,
        audit: AuditLog,
        settings: Settings,
    ) -> None:
        self.provider = provider
        self.confirmations = confirmations
        self.audit = audit
        self.settings = settings

    def decline(self, confirmation_id: str) -> None:
        """REFUSER: recorded, and nothing else happens."""
        self.confirmations.decline(confirmation_id)
        self.audit.record("HUMAN_DECLINED", action="none", result="Aucune action effectuée")

    async def confirm_and_execute(
        self, confirmation_id: str, limits: CostLimits
    ) -> UpgradeExecutionResult:
        confirmation = self.confirmations.confirm(confirmation_id)  # raises if invalid / expired
        self.audit.record("HUMAN_CONFIRMED", action=f"confirm option {confirmation.option_id}")
        result = await self.execute(confirmation, limits)
        self.confirmations.mark_executed(confirmation_id)
        self.audit.record(
            "UPGRADE_EXECUTION",
            decision=result.status.value,
            action=f"option {result.option_id}",
            result=result.message,
            details={"dry_run": self.settings.dry_run},
        )
        return result

    async def execute(
        self, confirmation: HumanConfirmation, limits: CostLimits
    ) -> UpgradeExecutionResult:
        try:
            # Re-read the official page: the offer may have changed since the alert.
            snapshot = await self.provider.take_snapshot()
            decision = evaluate_upgrade(snapshot, limits)
            still_valid = (
                decision.status is DecisionStatus.OPPORTUNITY
                and decision.option_id == confirmation.option_id
                and decision.cash_cost is not None
                and decision.miles_cost is not None
                and decision.cash_cost <= confirmation.max_cash
                and decision.miles_cost <= confirmation.max_miles
            )
            if not still_valid:
                return UpgradeExecutionResult(
                    status=ExecutionStatus.ABORTED,
                    message="L'offre n'est plus proposée telle que confirmée : aucune action.",
                    option_id=confirmation.option_id,
                    verification_snapshot_id=snapshot.snapshot_id,
                )
            option = next(o for o in snapshot.upgrade_options if o.option_id == decision.option_id)

            if self.settings.dry_run:
                return UpgradeExecutionResult(
                    status=ExecutionStatus.DRY_RUN_SIMULATED,
                    message=(
                        "DRY_RUN : aucune modification réelle. L'agent aurait accepté l'offre "
                        f"officielle {option.option_id} ({option.total_cash} € / "
                        f"{option.miles_price} Miles)."
                    ),
                    option_id=option.option_id,
                    verification_snapshot_id=snapshot.snapshot_id,
                )

            action = await self.provider.request_upgrade(option, confirmation)
            if not action.submitted:
                return UpgradeExecutionResult(
                    status=ExecutionStatus.ABORTED,
                    message=action.message,
                    option_id=option.option_id,
                )

            # Independent verification: only the airline can confirm the change.
            verification = await self.provider.take_snapshot()
            upgraded = (
                verification.confirmed_by_airline
                and len(verification.passengers) >= limits.passengers_target
                and all(
                    p.current_cabin.observed_value is Cabin.BUSINESS
                    for p in verification.passengers
                )
            )
            return UpgradeExecutionResult(
                status=(
                    ExecutionStatus.CONFIRMED_BY_AIRLINE
                    if upgraded
                    else ExecutionStatus.NOT_CONFIRMED_BY_AIRLINE
                ),
                message=(
                    "La compagnie affiche désormais Business pour tous les passagers."
                    if upgraded
                    else "Demande soumise, mais la compagnie n'affiche pas Business pour tous "
                    "les passagers. Vérifiez dans l'espace officiel."
                ),
                option_id=option.option_id,
                verification_snapshot_id=verification.snapshot_id,
            )
        except AirUpgradeError as exc:
            logger.warning("Execution stopped: %s", type(exc).__name__)
            return UpgradeExecutionResult(
                status=ExecutionStatus.ABORTED,
                message=f"Arrêt ({type(exc).__name__}) : aucune supposition, aucune action.",
                option_id=confirmation.option_id,
            )
