# Testing

Everything runs **without Azure and without Air France**.

```bash
cd backend
pytest                       # all tests (≈10 s, includes real Chromium on the mock page)
SKIP_BROWSER_TESTS=1 pytest  # without the browser tests
ruff check . && ruff format --check . && mypy   # lint + strict typing
```

Browser tests use `BROWSER_EXECUTABLE_PATH` (default `/opt/pw-browsers/chromium`), otherwise
Playwright's own Chromium (`python -m playwright install chromium`).

## Required tests

| Test | File |
|---|---|
| `test_three_business_free` | `tests/unit/test_decision_engine.py` |
| `test_two_business_only` | idem |
| `test_paid_upgrade` | idem |
| `test_miles_upgrade` | idem |
| `test_no_business` | idem |
| `test_missing_data` | idem |
| `test_conflicting_data` | idem |
| `test_human_confirmation_required` | `tests/unit/test_hitl_and_dry_run.py` |
| `test_redaction` | `tests/unit/test_privacy.py` |
| `test_no_credentials_in_logs` | idem |
| `test_dry_run` | `tests/unit/test_hitl_and_dry_run.py` |
| `test_monitoring_change` | `tests/unit/test_monitoring.py` |

## DRY_RUN scenarios

| Scenario | Input | Expected | Test |
|---|---|---|---|
| A | 3 Business, 0 €, 0 Miles | OPPORTUNITY | `test_three_business_free`, mock `free_upgrade_3_business` |
| B | 2 Business, 0 €, 0 Miles | NO_OPPORTUNITY | `test_two_business_only`, mock `two_business_available` |
| C | 3 Business, 250 € | NO_OPPORTUNITY | `test_paid_upgrade`, mock `paid_upgrade` |
| D | 3 Business, 30 000 Miles | NO_OPPORTUNITY | `test_miles_upgrade`, mock `miles_upgrade` |
| E | Business unavailable | NO_OPPORTUNITY | `test_no_business`, mock `business_unavailable` |
| F | 3 Business, 0/0, not confirmed by Air France | NO_OPPORTUNITY | `test_not_confirmed_by_airline`, mock `not_confirmed_by_airline` |

## MOCK AIR FRANCE

`data/mock/scenarios.json` (fictitious data) — Economy only, Economy + Business, 3 / 2 Business available,
paid, Miles, Miles + Cash, free, no upgrade, check-in closed / not open / open, login required, CAPTCHA,
not confirmed, conflicting data. Every scenario is asserted in `tests/unit/test_observation_and_mock.py`.

The same scenarios render as an HTML page (`app/browser/mock_page.py`) on which the **real**
Playwright `BrowserAgent` is tested end-to-end (`tests/integration/test_browser_agent_mock_site.py`):
reading, CAPTCHA/login detection, refusal without confirmation, stop on payment form, masked screenshots,
and refusal to click with unverified real selectors.

API end-to-end: `tests/integration/test_api.py`.
