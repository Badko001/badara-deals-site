# Air France workflow

## Principle

The agent sees exactly what **you** see in your own logged-in session, through the official website,
and nothing more. It uses no private API, no URL forging, no hidden endpoints.

## Steps

1. **Open** — `POST /api/session/start` (dashboard button). An isolated, visible Chromium opens on
   `AIRLINE_BASE_URL` with an ephemeral context.
2. **Manual login** — you type your credentials yourself. If a bot check appears, *you* solve it;
   the agent only detects it (`HUMAN_VERIFICATION_REQUIRED`) and waits.
   Timeout: `MANUAL_LOGIN_TIMEOUT_SECONDS`.
3. **Booking** — the agent follows the visible "My bookings" link (optionally matching the booking hint you
   typed, kept in memory only). If not found: `BookingNotFound` → open the booking yourself.
4. **Observe** — `BrowserAgent.read_page()` reads booking, passengers, cabin, Business availability and seats,
   upgrade offers, check-in status, messages. Missing element → `null`. Required element missing → `PageChanged` (stop).
5. **Decide** — ObservationEngine + DecisionEngine (+ optional LLM explanation).
6. **Monitor** — re-read every `POLL_INTERVAL_SECONDS` (≥ `MINIMUM_CHECK_INTERVAL`), tighter once check-in is open.
7. **Act (optional)** — only after CONFIRMER, only with verified selectors, see `ARCHITECTURE.md`.
8. **Verify** — success is claimed only if Air France now displays Business for all 3 passengers.

## OBSERVED vs INFERRED vs UNKNOWN

| Statement | Provenance |
|---|---|
| "3 sièges Business disponibles" displayed | OBSERVED |
| "Business probably has more seats" | INFERRED — never used as proof |
| Real inventory of Business seats | UNKNOWN unless officially displayed |

## Selector validation (required before any real click)

The real-site selectors in `backend/app/browser/selectors/airfrance.py` are heuristics
(`verified=False`). To validate them on your own session:

1. `cd backend && . .venv/bin/activate && playwright codegen https://wwws.airfrance.fr`
2. Log in yourself, open your booking, then the upgrade / check-in pages.
3. For each key of the `SelectorMap`, record a stable selector (prefer `data-testid`, roles, labels).
   Keep previous candidates as fallbacks.
4. Do **not** record anything inside payment forms, login fields or anti-bot widgets.
5. Run a read-only session with `DRY_RUN=true`, compare the dashboard with what you see.
6. Only then set `verified=True` (code review recommended), and keep `DRY_RUN=true` for a first real alert.

## Known limitations / TODO

* The real page structure, wording and offer presentation are not publicly documented: parsers recognise
  common French/English wordings; anything else stays `null`.
* Air France may present upgrades only at check-in, at the airport, or via operational decisions
  (non-public): such opportunities cannot be observed online and are out of scope.
* Eligibility is taken from per-passenger text, or from an official offer explicitly covering all passengers.
