# Security

## Non-negotiable rules

The system never: hacks or probes Air France, bypasses authentication / CAPTCHA / payment / Miles,
exploits a vulnerability, calls private undocumented APIs, injects data into the booking system,
forges a PNR / ticket / boarding pass (including visually), reserves seats artificially, uses
credentials it was not legitimately given, or retries an operation the airline refused.
Code-level enforcement: no HTTP client targets the airline; the browser only reads displayed text and
clicks official buttons; real clicks require a `HumanConfirmation` and a `verified` selector map.

## Secrets management

* `.env` is git-ignored; `.env.example` holds no value. Azure keys are `SecretStr` (never printed).
* **No airline password anywhere** — not in `.env`, not in prompts, not in the API.
* Production: Azure Key Vault references / Container Apps secrets, or managed identity for Azure OpenAI.

## Session management & credential isolation

* **Authentication layer** (`app/browser`) and **AI decision layer** (`app/agent`, `app/decision`) are separate.
  The LLM receives an allow-listed anonymised payload — never cookies, tokens, HTML or screenshots.
* Ephemeral browser context (in-memory cookies), destroyed on `session/close` or shutdown.
  No `storage_state` is written to disk (and such files are git-ignored).
* The user logs in manually; the agent only waits for a "logged in" marker.

## Logging policy

* One redacting filter on every handler (`app/security/logging.py`), including uvicorn's.
* Values seen on the page (names, PNR, tickets) are registered and redacted everywhere, plus
  patterns (e-mail, phones, ticket numbers, cards, `password=`, `token:`, `Bearer …`, contextual PNR / Flying Blue / passport / names).
* Audit trail stores `timestamp, event_type, decision, action, result` + redacted details; keys such as
  `password, token, cookie, credit_card, full_PNR, full_ticket_number` are dropped.
* API errors return a sanitised message only.

## PII minimisation

See `PRIVACY.md`. Passengers become `PASSENGER_00x`; PNR becomes `PNR_****123`.

## Screenshot policy

* Only when `DEBUG_MODE=true`. PII elements are masked by Playwright (`pii_mask` selectors).
* Files are `0600`, stored in `browser/screenshots/` (git-ignored), treated as sensitive data, never sent to the LLM.

## Retention policy

| Data | Retention |
|---|---|
| Debug screenshots | `SCREENSHOT_RETENTION_HOURS` (default 24 h), purged at start-up |
| Pending confirmations | `CONFIRMATION_TTL_SECONDS` (default 15 min), single use |
| Snapshots / audit (redacted) | Until the flight; delete `data/air_upgrade_agent.db` after travel |
| Browser session | Process lifetime only |

## Rate limiting

Real site: never more often than `MINIMUM_CHECK_INTERVAL`; exponential back-off on errors; monitoring stops
after 3 consecutive errors and asks the user.

## Incident handling

1. Stop: `POST /api/monitoring/stop`, then `POST /api/session/close`.
2. If a secret may have leaked: rotate Azure keys; change the airline password **on the airline site** and end sessions there.
3. Inspect the audit trail (`GET /api/audit`) — it contains no secrets by design.
4. Delete screenshots and the database if they may contain personal data.
5. Fix, add a regression test (e.g. in `tests/unit/test_privacy.py`), then resume in `DRY_RUN`.
