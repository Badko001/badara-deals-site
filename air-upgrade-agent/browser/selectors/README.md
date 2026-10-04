# Selectors

All selectors are centralised in **one** Python package (single source of truth):

- `backend/app/browser/selectors/airfrance.py` — real Air France site (`verified=False`: read-only until validated)
- `backend/app/browser/selectors/mock_airfrance.py` — MOCK AIR FRANCE page (verified by tests)
- `backend/app/browser/selectors/base.py` — structure (primary selector + ordered fallbacks)

Never define a selector anywhere else. Validation procedure: `docs/AIR_FRANCE_WORKFLOW.md`.
