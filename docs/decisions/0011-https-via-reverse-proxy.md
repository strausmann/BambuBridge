# 0011 — HTTPS terminated by a reverse proxy; bridge binds plain HTTP internally

- **Status:** Proposed
- **Date:** 2026-06-28
- **Deciders:** strausmann
- **Tags:** api, deploy

## Context
The PWA uses Web NFC / camera, which require a secure context (HTTPS). Terminating TLS in the app
adds cert-management complexity better handled by an existing proxy.

## Decision
We will bind the bridge to **plain HTTP internally** and require an **external reverse proxy**
(Pangolin/Traefik/Caddy/NPM) for **TLS**. HTTPS is mandatory in any reachable deployment.

## Options considered
- **Option A — TLS at the reverse proxy (chosen):** standard home-lab pattern, central cert mgmt,
  works with the existing Pangolin/Traefik stack.
- **Option B — TLS in the app:** duplicates cert handling; rejected.

## Consequences
- The bridge must always sit behind a proxy when exposed; the API-key is a complement to, not a
  replacement for, the HTTPS proxy.

## References
- `docs/api-guideline.md` §9; `docs/bambu-spoolman-bridge-concept.md` §9/§12; `app/main.py` (serves
  plain HTTP/static, no TLS).
