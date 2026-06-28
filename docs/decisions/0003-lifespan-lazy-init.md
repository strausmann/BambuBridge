# 0003 — Lazy-init the Bridge via FastAPI lifespan

- **Status:** Proposed
- **Date:** 2026-06-28
- **Deciders:** strausmann
- **Tags:** api, config

## Context
Constructing the Bridge at import time required `config.yaml` and opened MQTT connections, breaking
`uvicorn app.main:app` introspection and tests.

## Decision
We will construct the Bridge inside the FastAPI **`lifespan`** handler. Importing the module requires
no config and opens no connections; requests arriving before init get a clean **503**.

## Options considered
- **Option A — lifespan lazy-init (chosen):** import-safe, testable, idiomatic FastAPI.
- **Option B — module-level instantiation:** simple but breaks import/tests; deprecated `on_event`.

## Consequences
- `import app.main` is side-effect-free; tests run without hardware/config.
- A 503 middleware covers the brief startup/shutdown window.

## References
- BR-5 (`docs/review-findings-backlog.md`); PR #1; `app/main.py` (`lifespan`, `bridge=None`, 503
  middleware); `tests/test_app_lifespan_auth.py`.
