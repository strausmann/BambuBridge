# 0006 — LAN-MQTT primary, Cloud-MQTT fallback (`transport: auto|lan|cloud`)

- **Status:** Proposed
- **Date:** 2026-06-28
- **Deciders:** strausmann
- **Tags:** mqtt, config

## Context
Bambu printers expose telemetry over LAN MQTT (reliable, local) and Cloud MQTT (needs a token). The
bridge needs a predictable transport-selection policy.

## Decision
We will treat **LAN MQTT as the primary** transport and **Cloud MQTT as fallback**. `transport: auto`
uses LAN only if the printer is TCP-reachable on 8883, otherwise Cloud when a token exists; `lan` and
`cloud` force the respective path.

## Options considered
- **Option A — LAN primary, cloud fallback, `auto` reachability gate (chosen):** local-first,
  resilient, no cloud dependency for the core path.
- **Option B — cloud-only:** adds a hard cloud dependency; rejected (concept: cloud is enrichment).

## Consequences
- Core workflow works fully on LAN without cloud credentials.
- `auto` incurs a short TCP reachability probe at startup.

## References
- `docs/bambu-spoolman-bridge-concept.md` §3; `config.example.yaml` (`transport`, `bambu_account`);
  `app/main.py` `_make_client` (`tcp_reachable(host, 8883)` gate).
