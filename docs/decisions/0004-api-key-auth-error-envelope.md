# 0004 — X-API-Key auth on mutating routes + `{detail, error_code}` error envelope

- **Status:** Proposed
- **Date:** 2026-06-28
- **Deciders:** strausmann
- **Tags:** api

## Context
The API can drive printer-affecting actions; it needs authentication, with a HomeLab-behind-proxy
profile, and a consistent machine-readable error format.

## Decision
We will require **`X-API-Key`** on all mutating endpoints (key from `security.api_key` /
`BRIDGE_API_KEY`, constant-time compared). When no key is configured, auth is **disabled** (HomeLab
profile) with a startup warning. All errors use the envelope **`{ "detail": …, "error_code": … }`**.

## Options considered
- **Option A — X-API-Key dependency + envelope (chosen):** simple, proxy-friendly, consistent errors.
- **Option B — full OAuth/session auth:** overkill for a single-host home-lab bridge.

## Consequences
- HomeLab (no key) must sit behind a trusted reverse proxy; workshop profile sets a key.
- Error envelope is the contract for all endpoints (see api-guideline §8).

## References
- BR-1 (`docs/review-findings-backlog.md`); PR #1; `docs/api-guideline.md` §8; `config.example.yaml`
  `security:`; `app/main.py` (`require_api_key`, `APIError`, handler); tests.
