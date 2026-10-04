"""Privacy layer: data minimisation and automatic redaction.

Everything that leaves the process boundary (logs, audit trail, errors,
LLM prompts, temporary files) goes through :func:`redact_sensitive_data` or one
of the :class:`PrivacyManager` helpers.

Two complementary mechanisms:

1. *Known values*: personal values actually read on the page (names, PNR,
   ticket numbers...) are registered at runtime and replaced everywhere.
2. *Patterns & keys*: regexes for e-mails, phones, tickets, cards, contextual
   PNR / names / secrets, and dictionary keys that are sensitive by nature.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class SensitiveKind(StrEnum):
    NAME = "NAME"
    PNR = "PNR"
    TICKET = "TICKET"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    FLYING_BLUE = "FLYING_BLUE"
    PASSPORT = "PASSPORT"
    ADDRESS = "ADDRESS"
    SECRET = "SECRET"  # noqa: S105 - enum label, not a credential


REDACTED = "[REDACTED]"

# Keys whose values are secrets: always fully removed.
_SECRET_KEY_PARTS = (
    "password",
    "passwd",
    "pwd",
    "motdepasse",
    "token",
    "secret",
    "apikey",
    "authorization",
    "cookie",
    "sessionid",
    "storagestate",
    "creditcard",
    "cardnumber",
    "cvv",
    "cvc",
    "iban",
)

# Keys whose values are personal data.
_PII_KEYS: dict[str, SensitiveKind] = {
    "name": SensitiveKind.NAME,
    "firstname": SensitiveKind.NAME,
    "lastname": SensitiveKind.NAME,
    "fullname": SensitiveKind.NAME,
    "givenname": SensitiveKind.NAME,
    "surname": SensitiveKind.NAME,
    "prenom": SensitiveKind.NAME,
    "nom": SensitiveKind.NAME,
    "passengername": SensitiveKind.NAME,
    "nametext": SensitiveKind.NAME,
    "email": SensitiveKind.EMAIL,
    "mail": SensitiveKind.EMAIL,
    "phone": SensitiveKind.PHONE,
    "phonenumber": SensitiveKind.PHONE,
    "mobile": SensitiveKind.PHONE,
    "telephone": SensitiveKind.PHONE,
    "passport": SensitiveKind.PASSPORT,
    "passportnumber": SensitiveKind.PASSPORT,
    "address": SensitiveKind.ADDRESS,
    "adresse": SensitiveKind.ADDRESS,
    "flyingblue": SensitiveKind.FLYING_BLUE,
    "flyingbluenumber": SensitiveKind.FLYING_BLUE,
    "frequentflyernumber": SensitiveKind.FLYING_BLUE,
    "birthdate": SensitiveKind.NAME,
    "dateofbirth": SensitiveKind.NAME,
    "ticket": SensitiveKind.TICKET,
    "ticketnumber": SensitiveKind.TICKET,
    "pnr": SensitiveKind.PNR,
    "bookingreference": SensitiveKind.PNR,
    "bookingreferencetext": SensitiveKind.PNR,
    "recordlocator": SensitiveKind.PNR,
}

# Keys never sent to the LLM at all (on top of secrets and PII).
_LLM_DROPPED_KEYS = {"internalid", "screenshot", "screenshotpath", "image", "html", "rawhtml"}

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_TICKET_RE = re.compile(r"\b(\d{3})[- ]?(\d{10})\b")
_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_PHONE_INTL_RE = re.compile(r"\+\d{1,3}(?:[ .-]?\d{1,4}){2,5}\b")
_PHONE_FR_RE = re.compile(r"\b0\d(?:[ .-]?\d{2}){4}\b")
_SECRET_KV_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|mot de passe|token|secret|api[_-]?key|authorization|"
    r"cookie|set-cookie|session[_-]?id)(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|\S+)"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_PNR_CONTEXT_RE = re.compile(
    r"(?i)\b(pnr|booking\s+reference|booking\s+ref|record\s+locator|"
    r"référence(?:\s+de\s+réservation)?|code\s+de\s+réservation)(\s*[:#n°]*\s*)([A-Z0-9]{5,8})\b"
)
_FB_CONTEXT_RE = re.compile(
    r"(?i)\b(flying\s*blue|frequent\s+flyer)(\s*(?:n°|no\.?|number|numéro)?\s*[:#]?\s*)(\d{6,12})\b"
)
_PASSPORT_CONTEXT_RE = re.compile(
    r"(?i)\b(passport|passeport)(\s*(?:n°|no\.?|number|numéro)?\s*[:#]?\s*)([A-Z0-9]{6,9})\b"
)
_TITLE_NAME_RE = re.compile(
    r"\b(M\.|Mr\.?|Mrs\.?|Ms\.?|Mme\.?|Mlle\.?|Monsieur|Madame|Mademoiselle|MR|MRS|MS)"
    r"(\s+)[A-ZÀ-Ý][\wÀ-ÿ'-]+(?:\s+[A-ZÀ-Ý][\wÀ-ÿ'-]+){0,2}"
)
_LABELLED_NAME_RE = re.compile(
    r"(?i)\b(passenger\s+name|full\s+name|name|nom|prénom|passager)(\s*[:=]\s*)([^\n,;|]+)"
)


def _norm_key(key: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _is_secret_key(key: object) -> bool:
    norm = _norm_key(key)
    return any(part in norm for part in _SECRET_KEY_PARTS)


class PrivacyManager:
    """Thread-safe registry of known sensitive values + redaction helpers."""

    def __init__(self) -> None:
        self._known: dict[str, str] = {}
        self._lock = threading.Lock()
        self._known_re: re.Pattern[str] | None = None

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def redact_pnr(pnr: str) -> str:
        clean = re.sub(r"\s", "", pnr)
        return f"PNR_****{clean[-3:]}" if len(clean) > 3 else "PNR_****"

    @staticmethod
    def redact_ticket_number(ticket: str) -> str:
        digits = re.sub(r"\D", "", ticket)
        if len(digits) <= 4:
            return "TICKET_****"
        return "TICKET_" + "*" * (len(digits) - 4) + digits[-4:]

    @staticmethod
    def redact_name(_name: str = "") -> str:
        return "[NAME]"

    @staticmethod
    def redact_email(_email: str = "") -> str:
        return "[EMAIL]"

    @staticmethod
    def redact_phone(_phone: str = "") -> str:
        return "[PHONE]"

    def replacement_for(self, kind: SensitiveKind, value: str) -> str:
        match kind:
            case SensitiveKind.PNR:
                return self.redact_pnr(value)
            case SensitiveKind.TICKET:
                return self.redact_ticket_number(value)
            case SensitiveKind.NAME:
                return self.redact_name(value)
            case SensitiveKind.EMAIL:
                return self.redact_email(value)
            case SensitiveKind.PHONE:
                return self.redact_phone(value)
            case SensitiveKind.SECRET:
                return REDACTED
            case _:
                return f"[{kind.value}]"

    # ----------------------------------------------------------------- registry
    def register(self, value: str | None, kind: SensitiveKind) -> None:
        """Remember a personal value seen at runtime so it is redacted everywhere."""
        if not value:
            return
        value = value.strip()
        if len(value) < 2:
            return
        with self._lock:
            self._known[value] = self.replacement_for(kind, value)
            if kind is SensitiveKind.NAME:
                # Also redact each part of a multi-word name ("Jean DUPONT").
                for part in re.split(r"\s+", value):
                    if len(part) >= 3:
                        self._known.setdefault(part, self.redact_name(part))
            self._known_re = None

    def clear(self) -> None:
        with self._lock:
            self._known.clear()
            self._known_re = None

    def _known_pattern(self) -> re.Pattern[str] | None:
        with self._lock:
            if self._known_re is None and self._known:
                alternatives = sorted(self._known, key=len, reverse=True)
                self._known_re = re.compile(
                    r"(?<![\w])(" + "|".join(re.escape(v) for v in alternatives) + r")(?![\w])",
                    re.IGNORECASE,
                )
            return self._known_re

    # ------------------------------------------------------------- sanitizers
    def sanitize_text(self, text: str) -> str:
        if not text:
            return text
        pattern = self._known_pattern()
        if pattern is not None:
            lookup = {k.lower(): v for k, v in self._known.items()}
            text = pattern.sub(lambda m: lookup.get(m.group(0).lower(), REDACTED), text)

        text = _BEARER_RE.sub(f"Bearer {REDACTED}", text)
        text = _SECRET_KV_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
        text = _EMAIL_RE.sub(self.redact_email(), text)
        text = _TICKET_RE.sub(lambda m: self.redact_ticket_number(m.group(0)), text)
        text = _CARD_RE.sub("[CARD]", text)
        text = _PHONE_INTL_RE.sub(self.redact_phone(), text)
        text = _PHONE_FR_RE.sub(self.redact_phone(), text)
        text = _PNR_CONTEXT_RE.sub(
            lambda m: f"{m.group(1)}{m.group(2)}{self.redact_pnr(m.group(3))}", text
        )
        text = _FB_CONTEXT_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[FLYING_BLUE]", text)
        text = _PASSPORT_CONTEXT_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[PASSPORT]", text)
        text = _TITLE_NAME_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[NAME]", text)
        text = _LABELLED_NAME_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[NAME]", text)
        return text

    def sanitize_log(self, message: str) -> str:
        return self.sanitize_text(message)

    def sanitize(self, data: Any) -> Any:
        """Deep-redact any structure (dict / list / str / pydantic model)."""
        if isinstance(data, BaseModel):
            return self.sanitize(data.model_dump(mode="json"))
        if isinstance(data, Mapping):
            out: dict[str, Any] = {}
            for key, value in data.items():
                skey = str(key)
                if _is_secret_key(skey):
                    out[skey] = REDACTED
                    continue
                kind = _PII_KEYS.get(_norm_key(skey))
                if kind is not None and value is not None:
                    out[skey] = (
                        self.replacement_for(kind, str(value))
                        if isinstance(value, str | int)
                        else f"[{kind.value}]"
                    )
                    continue
                out[skey] = self.sanitize(value)
            return out
        if isinstance(data, list | tuple | set):
            return [self.sanitize(v) for v in data]
        if isinstance(data, str):
            return self.sanitize_text(data)
        return data

    def sanitize_llm_payload(self, payload: Any) -> Any:
        """Stricter than :meth:`sanitize`: sensitive keys are *removed*, not masked."""
        if isinstance(payload, BaseModel):
            return self.sanitize_llm_payload(payload.model_dump(mode="json"))
        if isinstance(payload, Mapping):
            out: dict[str, Any] = {}
            for key, value in payload.items():
                norm = _norm_key(key)
                if _is_secret_key(key) or norm in _PII_KEYS or norm in _LLM_DROPPED_KEYS:
                    continue
                out[str(key)] = self.sanitize_llm_payload(value)
            return out
        if isinstance(payload, list | tuple | set):
            return [self.sanitize_llm_payload(v) for v in payload]
        if isinstance(payload, str):
            return self.sanitize_text(payload)
        return payload


_default = PrivacyManager()


def get_privacy_manager() -> PrivacyManager:
    return _default


def redact_sensitive_data(data: Any) -> Any:
    """Single entry point used by logs, audit, errors, LLM payloads and files."""
    return _default.sanitize(data)
