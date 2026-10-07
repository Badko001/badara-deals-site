from __future__ import annotations

import os

# Tests never touch a real database file, Azure or the real airline.
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("DRY_RUN", "true")
os.environ.setdefault("PROVIDER", "mock")
for key in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT"):
    os.environ.pop(key, None)

import pytest  # noqa: E402

from app.config import Settings  # noqa: E402
from app.services.container import Container  # noqa: E402


def make_container(scenario: str = "free_upgrade_3_business", **overrides: object) -> Container:
    overrides.setdefault("database_url", "sqlite://")
    settings = Settings(
        mock_scenario=scenario,
        _env_file=None,  # type: ignore[call-arg]
        **overrides,  # type: ignore[arg-type]
    )
    return Container.build(settings)


@pytest.fixture
def container() -> Container:
    return make_container()
