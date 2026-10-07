# Privacy — data minimisation

The AI does not need to know who you are to tell whether a free Business upgrade exists.

## What happens to personal data

| Data read on the page | Kept as | Where it goes |
|---|---|---|
| Passenger names | `PASSENGER_001/002/003` + non-reversible HMAC internal id (per-process salt) | Registered for redaction, then discarded |
| Booking reference (PNR) `ABC123` | `PNR_****123` | Same. A reference typed in the dashboard stays in memory only; only the redacted form is stored |
| Ticket number `0571234567890` | `TICKET_*********7890` | Same |
| E-mail, phone, Flying Blue, passport, address | `[EMAIL]`, `[PHONE]`, `[FLYING_BLUE]`, `[PASSPORT]`… | Never stored |
| Password, cookies, tokens, card data | — | Never read, never stored, `[REDACTED]` if ever encountered |

## PrivacyManager (`backend/app/security/privacy.py`)

`redact_pnr()`, `redact_ticket_number()`, `redact_name()`, `redact_email()`, `redact_phone()`,
`sanitize_log()`, `sanitize_llm_payload()`, and the single entry point `redact_sensitive_data()`
used for logs, traces, errors, audit, LLM prompts, persisted snapshots and notifications.

## LLM payload

Built from an **allow-list** (`build_llm_view`): flight number, airports, anonymised passenger ids with
cabin/eligibility provenance, seat counts, offer prices, check-in state, sanitised page messages,
limits and the engine decision. `sanitize_llm_payload()` then **removes** (not masks) any sensitive key.
Test: `tests/unit/test_llm_orchestrator.py::test_no_personal_data_sent_to_llm`.

## Screenshots

Debug only, PII masked, owner-only permissions, auto-purged, never sent to the LLM.
