"""MOCK AIR FRANCE - a fake airline used for tests, demos and DRY_RUN.

It behaves like the airline's system: it shows a booking page (in raw form), and
when its official offer is accepted it updates the booking itself. Nothing here
touches the real Air France website.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.booking.observation import ObservationEngine
from app.booking.providers.base import AirlineProvider
from app.browser.raw import RawPageObservation
from app.config import PROJECT_ROOT
from app.models import SnapshotSource, UpgradeOption
from app.models.actions import HumanConfirmation, ProviderActionResult

DEFAULT_SCENARIOS_PATH = PROJECT_ROOT / "data" / "mock" / "scenarios.json"


class MockScenario(BaseModel):
    name: str
    description: str
    confirmed_by_airline: bool = True
    page: RawPageObservation


def load_scenarios(path: Path = DEFAULT_SCENARIOS_PATH) -> dict[str, MockScenario]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    base = data["base"]
    scenarios: dict[str, MockScenario] = {}
    for name, spec in data["scenarios"].items():
        page = copy.deepcopy(base)
        page.update(copy.deepcopy(spec.get("overrides", {})))
        scenarios[name] = MockScenario(
            name=name,
            description=spec.get("description", name),
            confirmed_by_airline=spec.get("confirmed_by_airline", True),
            page=RawPageObservation.model_validate(page),
        )
    return scenarios


class MockAirFrance:
    """Stateful fake airline system."""

    def __init__(self, scenario: str = "free_upgrade_3_business", path: Path | None = None) -> None:
        self.scenarios = load_scenarios(path or DEFAULT_SCENARIOS_PATH)
        self.page_reads = 0
        self.accepted_offers: list[str] = []
        self.set_scenario(scenario)

    def set_scenario(self, name: str) -> None:
        if name not in self.scenarios:
            raise KeyError(f"Unknown mock scenario: {name}")
        self.scenario_name = name
        self._scenario = self.scenarios[name]
        self._page = self._scenario.page.model_copy(deep=True)

    @property
    def confirmed_by_airline(self) -> bool:
        return self._scenario.confirmed_by_airline

    def current_page(self) -> RawPageObservation:
        self.page_reads += 1
        return self._page.model_copy(deep=True)

    def accept_offer(self, offer_id: str) -> bool:
        """Simulates the airline accepting its own offer and updating the booking."""
        offer = next((o for o in self._page.upgrade_offers if o.offer_id == offer_id), None)
        if offer is None or not offer.has_accept_button:
            return False
        self.accepted_offers.append(offer_id)
        for row in self._page.passenger_rows:
            row.cabin_text = "Business"
        self._page.cabin_text = "Business"
        self._page.upgrade_offers = []
        self._page.messages = ["Votre surclassement en Business est confirmé."]
        return True


class MockAirFranceProvider(AirlineProvider):
    name = "mock-airfrance"
    source = SnapshotSource.MOCK_AIR_FRANCE
    enforce_rate_limit = False

    def __init__(
        self, mock: MockAirFrance | None = None, observation: ObservationEngine | None = None
    ) -> None:
        super().__init__(observation)
        self.mock = mock or MockAirFrance()

    async def read_raw(self) -> RawPageObservation:
        return self.mock.current_page()

    def is_confirmed_by_airline(self) -> bool:
        return self.mock.confirmed_by_airline

    async def _accept_official_offer(
        self, option: UpgradeOption, confirmation: HumanConfirmation
    ) -> ProviderActionResult:
        accepted = self.mock.accept_offer(option.option_id)
        return ProviderActionResult(
            submitted=accepted,
            message="Offre acceptée par le mock" if accepted else "Offre absente du mock",
        )
