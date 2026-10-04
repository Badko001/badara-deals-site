"""Privacy layer: redaction of logs, structures and LLM payloads."""

from __future__ import annotations

import io
import logging
from collections.abc import Iterator

import pytest

from app.security.logging import configure_logging
from app.security.privacy import PrivacyManager, SensitiveKind, get_privacy_manager

# Fictitious personal data only.
FAKE_NAME = "Jean-Baptiste DIALLO"
FAKE_EMAIL = "jb.diallo@example.com"
FAKE_PNR = "ABC123"
FAKE_TICKET = "0571234567890"


@pytest.fixture
def pm() -> PrivacyManager:
    return PrivacyManager()


@pytest.fixture
def clean_default() -> Iterator[PrivacyManager]:
    manager = get_privacy_manager()
    manager.clear()
    yield manager
    manager.clear()


def test_redaction(pm: PrivacyManager) -> None:
    assert pm.redact_pnr(FAKE_PNR) == "PNR_****123"
    assert pm.redact_ticket_number(FAKE_TICKET) == "TICKET_*********7890"
    assert pm.redact_email(FAKE_EMAIL) == "[EMAIL]"
    assert pm.redact_phone("+221 77 123 45 67") == "[PHONE]"
    assert pm.redact_name(FAKE_NAME) == "[NAME]"

    text = (
        f"Booking reference: {FAKE_PNR}, ticket {FAKE_TICKET}, mail {FAKE_EMAIL}, "
        "tel +221 77 123 45 67 / 06 12 34 56 78, Flying Blue n° 1234567890, "
        "passeport: AB1234567, Mme Awa NDIAYE"
    )
    out = pm.sanitize_text(text)
    for secret in (
        FAKE_PNR,
        FAKE_TICKET,
        FAKE_EMAIL,
        "77 123",
        "06 12",
        "1234567890",
        "AB1234567",
        "Awa",
        "NDIAYE",
    ):
        assert secret not in out, secret
    assert "PNR_****123" in out
    assert "TICKET_*********7890" in out


def test_registered_values_are_redacted_everywhere(pm: PrivacyManager) -> None:
    pm.register(FAKE_NAME, SensitiveKind.NAME)
    pm.register(FAKE_PNR, SensitiveKind.PNR)
    out = pm.sanitize_text(f"Passenger {FAKE_NAME.upper()} on {FAKE_PNR.lower()} seat 32A")
    assert "DIALLO" not in out.upper()
    assert "abc123" not in out
    assert "seat 32A" in out


def test_dates_and_flights_are_not_over_redacted(pm: PrivacyManager) -> None:
    text = "AF719 DSS-CDG 2026-10-05 23:55, 3 Business seats, 0 EUR, 0 Miles"
    assert pm.sanitize_text(text) == text


def test_structures_are_deep_redacted(pm: PrivacyManager) -> None:
    data = {
        "password": "hunter2",
        "nested": {"Cookie": "sid=xyz", "email": FAKE_EMAIL, "pnr": FAKE_PNR},
        "passengers": [{"first_name": "Awa", "anonymized_id": "PASSENGER_001"}],
        "ticket_number": FAKE_TICKET,
    }
    out = pm.sanitize(data)
    assert out["password"] == "[REDACTED]"
    assert out["nested"]["Cookie"] == "[REDACTED]"
    assert out["nested"]["email"] == "[EMAIL]"
    assert out["nested"]["pnr"] == "PNR_****123"
    assert out["passengers"][0] == {"first_name": "[NAME]", "anonymized_id": "PASSENGER_001"}
    assert out["ticket_number"] == "TICKET_*********7890"


def test_llm_payload_drops_personal_keys(pm: PrivacyManager) -> None:
    payload = {
        "flight": "AF719",
        "full_name": FAKE_NAME,
        "internal_id": "abc",
        "api_key": "k",
        "screenshot_path": "/tmp/x.png",
        "messages": [f"Contact {FAKE_EMAIL}"],
    }
    out = pm.sanitize_llm_payload(payload)
    assert set(out) == {"flight", "messages"}
    assert out["messages"] == ["Contact [EMAIL]"]


def test_no_credentials_in_logs(clean_default: PrivacyManager) -> None:
    stream = io.StringIO()
    handler = configure_logging(stream=stream)
    try:
        clean_default.register(FAKE_NAME, SensitiveKind.NAME)
        log = logging.getLogger("test.credentials")
        log.info("login password=Sup3rS3cret! token: abc.def.ghi")
        log.info("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig")
        log.info("cookie=%s for %s", "session=deadbeef", FAKE_NAME)
        log.warning("pnr %s ticket %s", FAKE_PNR, FAKE_TICKET)
        try:
            raise RuntimeError(f"failed for {FAKE_EMAIL} with password={'x' * 8}")
        except RuntimeError:
            log.exception("boom")
    finally:
        logging.getLogger().removeHandler(handler)

    output = stream.getvalue()
    for leaked in (
        "Sup3rS3cret",
        "abc.def.ghi",
        "eyJhbGci",
        "deadbeef",
        "DIALLO",
        FAKE_PNR,
        FAKE_TICKET,
        FAKE_EMAIL,
        "xxxxxxxx",
    ):
        assert leaked not in output, leaked
    assert "[REDACTED]" in output
