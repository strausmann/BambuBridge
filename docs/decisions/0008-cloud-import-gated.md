# 0008 — Bambu Cloud library import is unconfirmed/gated until capture-verified

- **Status:** Proposed
- **Date:** 2026-06-28
- **Deciders:** strausmann
- **Tags:** cloud, docs

## Context
The Bambu Cloud filament-library endpoint is reverse-engineering-derived and not yet confirmed; we
must not present it as production-ready.

## Decision
We will treat the Cloud import endpoint (`/v1/user-service/my/filament/v2`) as a **hypothesis** —
config-overridable and **file-testable** (saved capture) — and **not declare it go-live** until
confirmed by capture/RE. Imports remain idempotent via RFID/`cloud_id`.

## Options considered
- **Option A — gated + file-based escape hatch, labeled unconfirmed (chosen):** honest, testable
  offline, safe.
- **Option B — ship as a supported feature:** misleading; depends on an unverified endpoint.

## Consequences
- Docs label it "blocked/gated, untested"; live import needs a token + confirmation.
- Provides a `source=file` path for offline testing.

## References
- `docs/api-guideline.md` (blockiert marker); `docs/bambu-spoolman-bridge-concept.md` §6/§6.1;
  `docs/no-devmode-capability-matrix.md`; BR-6; `app/cloud_library.py`, `app/main.py`
  `run_cloud_import`.
