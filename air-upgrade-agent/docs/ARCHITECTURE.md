# Architecture

```
USER ──► React dashboard ──► FastAPI (app/api)
                                 │
                 ┌───────────────┼──────────────────────┐
                 ▼               ▼                      ▼
        MonitoringEngine   UpgradeExecutor        RuntimeSettings / Audit
                 │               │  (HITL only)
                 ▼               ▼
         AirlineProvider ◄───────┘        LLMOrchestrator (Azure, optional,
        (AirFrance | Mock)                 explains, may only be MORE prudent)
                 │                                  ▲
       BrowserAgent (Playwright)                    │
                 │                                  │
     RawPageObservation ─► ObservationEngine ─► BookingSnapshot ─► DecisionEngine
        (raw texts, PII)      (redact, parse,        (OBSERVED/      (deterministic
                               provenance)            INFERRED/       authority)
                                                      UNKNOWN)
```

## Layers (`backend/app`)

| Package | Role |
|---|---|
| `browser/` | **Authentication layer** + page reading. `agent.py` (Playwright), `selectors/` (only place for selectors, with fallbacks), `raw.py` (raw texts), `mock_page.py` (simulated airline page). |
| `booking/observation.py` | `ObservationEngine`: raw page → `BookingSnapshot`. Registers PII for redaction, anonymises passengers (`PASSENGER_001`…), never invents (unparseable → `null`/`UNKNOWN`). |
| `booking/providers/` | `AirlineProvider` interface (`get_booking`, `get_upgrade_options`, `get_cabin_availability`, `get_checkin_status`, `request_upgrade`), `AirFranceProvider`, `MockAirFranceProvider`. |
| `decision/` | `evaluate_upgrade()` and `find_three_passenger_opportunity()` — pure functions. |
| `agent/orchestrator.py` | **AI decision layer**: LLM explanation with strict schema + guardrails. Never sees credentials. |
| `monitoring/` | `MonitoringEngine`: `start_monitoring`, `stop_monitoring`, `take_snapshot`, `compare_snapshots`, `detect_opportunity`, `detect_change`. Rate limit, back-off. |
| `notifications/` | `NotificationService` (memory/log/webhook): `OPPORTUNITY_FOUND`, `OPPORTUNITY_CHANGED`, `CHECKIN_OPEN`, `NO_LONGER_AVAILABLE`, `ACTION_REQUIRED`. |
| `services/` | DB (SQLAlchemy), audit trail, confirmations (HITL), executor, runtime limits, DI container. |
| `security/` | `PrivacyManager`, `redact_sensitive_data()`, redacting log filter. |
| `models/` | Pydantic models: `Passenger`, `Flight`, `Booking`, `UpgradeOption`, `BookingSnapshot`, `UpgradeDecision`, `HumanConfirmation`. |

## Decision rule (three-passenger optimizer)

```
OPPORTUNITY  ⇔  data confirmed by the airline (official source)
              ∧ Business availability OBSERVED = true
              ∧ business_seats_observed ≥ 3          (OBSERVED, never inferred)
              ∧ 3 passengers OBSERVED as eligible
              ∧ ONE official offer, observed, available, covering ≥ 3 passengers
              ∧ cash (incl. Miles+Cash part) known and ≤ cash_limit
              ∧ miles known and ≤ miles_limit
              ∧ no conflicting observations
```

* Valid offer but no official button → `ACTION_REQUIRED` (user accepts it through the official channel).
* Login / CAPTCHA / unexpected page → `ACTION_REQUIRED`, nothing is bypassed.
* Unknown price ≠ free. Inferred value ≠ observed value.

## Real action flow (Human-in-the-loop)

1. Monitoring finds `OPPORTUNITY` → a **pending confirmation** (single use, expires after `CONFIRMATION_TTL_SECONDS`) + alert.
2. User clicks **CONFIRMER** → `ConfirmationService.confirm()` produces the only `HumanConfirmation` object.
3. Executor **re-reads** the official page and re-evaluates; any change (price, offer gone) → `ABORTED`.
4. `DRY_RUN=true` → `DRY_RUN_SIMULATED`, nothing else.
5. Otherwise the provider clicks the official button; it stops on any payment form / cost above the confirmed amount; Air France selectors must be `verified`.
6. Independent verification: success (`CONFIRMED_BY_AIRLINE`) only if the airline now shows Business for every passenger; else `NOT_CONFIRMED_BY_AIRLINE`.

**REFUSER** → recorded, no action.

## Adding an airline

1. `browser/selectors/<airline>.py` with a `SelectorMap`.
2. `booking/providers/<airline>.py` subclassing `AirlineProvider` (`read_raw`, `is_confirmed_by_airline`, `_accept_official_offer`).
3. Add a `ProviderName` value and wire it in `services/container.py`.

The decision engine, privacy layer, monitoring, HITL and UI are airline-agnostic.

## Persistence

SQLite (MVP) via SQLAlchemy 2. PostgreSQL: set `DATABASE_URL=postgresql+psycopg://…` and add `psycopg[binary]`
(tables are created at start-up; introduce Alembic before the first schema change in production).
