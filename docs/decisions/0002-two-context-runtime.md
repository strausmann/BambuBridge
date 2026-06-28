# 0002 — Single-process, two-context runtime (MQTT ingest threads + FastAPI)

- **Status:** Proposed
- **Date:** 2026-06-28
- **Deciders:** strausmann
- **Tags:** mqtt, api

## Context
The bridge must continuously ingest printer telemetry (LAN/Cloud MQTT, one client per printer) and
serve an HTTP API/PWA, sharing live state (trays, AMS identity, calibration) between them.

## Decision
We will run the bridge as **one process** that combines background MQTT ingest (one client/thread per
printer) with a FastAPI HTTP app, sharing in-process state guarded by a lock.

## Options considered
- **Option A — single process, MQTT thread(s) + FastAPI (chosen):** simplest deployment, shared
  in-memory state, low latency.
- **Option B — separate ingest and API services + IPC/DB:** more moving parts, premature for a
  single-host home-lab bridge.

## Consequences
- Shared mutable state must be lock-guarded (see the locking follow-up, BR-2).
- Scales per host/printer set; not horizontally — acceptable for the use case.

## References
- `docs/bambu-spoolman-bridge-concept.md` §1; `docs/database-guideline.md` (one process, MQTT-thread +
  FastAPI threadpool); `app/main.py` (per-printer clients, shared `live_trays`, `threading.Lock`).
