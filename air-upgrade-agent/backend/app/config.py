"""Application configuration.

Everything is read from environment variables (or a local ``.env`` file that is
git-ignored). The user's airline password is *never* part of the configuration:
authentication is always performed manually by the user in an isolated browser.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class FareProviderName(StrEnum):
    MOCK = "mock"
    DUFFEL = "duffel"


class ProviderName(StrEnum):
    MOCK = "mock"
    AIR_FRANCE = "airfrance"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Azure / Microsoft Foundry (all optional: the system works without them)
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: SecretStr | None = None
    azure_openai_deployment: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    azure_foundry_project: str | None = None

    # --- Safety switches
    dry_run: bool = True
    debug_mode: bool = False

    # --- Financial constraints ("FREE UPGRADE" mode by default)
    cash_limit: Decimal = Field(default=Decimal("0"), ge=0)
    miles_limit: int = Field(default=0, ge=0)
    passengers_target: int = Field(default=3, ge=1, le=9)

    # --- Monitoring cadence (seconds)
    poll_interval_seconds: int = Field(default=300, ge=1)
    minimum_check_interval: int = Field(default=120, ge=1)
    maximum_check_interval: int = Field(default=3600, ge=1)

    # --- Provider / browser
    provider: ProviderName = ProviderName.MOCK
    mock_scenario: str = "free_upgrade_3_business"
    airline_base_url: str = "https://wwws.airfrance.fr"
    browser_headless: bool = False  # manual login requires a visible browser
    browser_executable_path: str | None = None
    manual_login_timeout_seconds: int = Field(default=600, ge=10)
    navigation_timeout_ms: int = Field(default=30_000, ge=1000)

    # --- Price watch (published fares only, from an authorised API)
    fare_provider: FareProviderName = FareProviderName.MOCK
    duffel_api_token: SecretStr | None = None
    fare_airline_filter: str = "AF"  # IATA code; empty = all airlines
    price_watch_interval_seconds: int = Field(default=10_800, ge=3600)  # never more than hourly
    price_drop_alert_percent: Decimal = Field(default=Decimal("10"), gt=0, le=90)
    max_dates_per_watch: int = Field(default=7, ge=1, le=14)

    # --- Storage
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'data' / 'air_upgrade_agent.db'}"
    screenshot_dir: Path = PROJECT_ROOT / "browser" / "screenshots"
    screenshot_retention_hours: int = Field(default=24, ge=1)
    confirmation_ttl_seconds: int = Field(default=900, ge=30)

    # --- API
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @model_validator(mode="after")
    def _check_intervals(self) -> Settings:
        if self.minimum_check_interval > self.maximum_check_interval:
            raise ValueError("MINIMUM_CHECK_INTERVAL must be <= MAXIMUM_CHECK_INTERVAL")
        return self

    @property
    def azure_configured(self) -> bool:
        return bool(
            self.azure_openai_endpoint
            and self.azure_openai_api_key
            and self.azure_openai_deployment
        )

    def effective_poll_interval(self) -> int:
        """Poll interval clamped to the [minimum, maximum] window."""
        return max(
            self.minimum_check_interval,
            min(self.poll_interval_seconds, self.maximum_check_interval),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
