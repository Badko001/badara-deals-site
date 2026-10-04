"""Domain errors.

Rule: after a critical error the system stops and reports. It never "guesses"
the state of the booking to continue.
"""

from __future__ import annotations


class AirUpgradeError(Exception):
    """Base class. Messages must never contain personal data."""

    critical: bool = True


class AgentTimeoutError(AirUpgradeError):
    """A page or an action did not complete in time."""


class AuthenticationRequired(AirUpgradeError):
    """The user must log in manually in the isolated browser."""


class HumanVerificationRequired(AirUpgradeError):
    """A CAPTCHA / bot check is shown. It is never bypassed: the user solves it."""


class BookingNotFound(AirUpgradeError):
    """The requested booking is not visible in the user's account."""


class PageChanged(AirUpgradeError):
    """The airline page structure no longer matches the known workflow."""


class SelectorNotFound(AirUpgradeError):
    """No primary nor fallback selector matched."""

    def __init__(self, key: str) -> None:
        super().__init__(f"No selector matched for '{key}'")
        self.key = key


class UnexpectedAirFrancePage(AirUpgradeError):
    """The browser landed on a page that is not part of the expected workflow."""


class UpgradeUnavailable(AirUpgradeError):
    """The official upgrade offer is not (or no longer) available."""


class InsufficientBusinessSeats(AirUpgradeError):
    """Fewer Business seats are visible than passengers to upgrade."""


class HumanConfirmationRequired(AirUpgradeError):
    """A real action was attempted without a valid explicit human confirmation."""


class CostLimitExceeded(AirUpgradeError):
    """The offer requires cash or miles above the configured limits."""
