# Architecture Decision Records (ADRs)

Binding decisions for BambuBridge live here, one file per decision, in the
[Nygard format](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).

## Rules
- **One file per decision**, named `NNNN-short-slug.md` (zero-padded, sequential).
- A file **stays once written**. To change a decision, write a **new** ADR that
  supersedes the old one, and set the old one's status to `Superseded by NNNN`.
- Copy [`_template.md`](_template.md) for new ADRs.
- Decisions that change project direction or conventions must also be reflected in the
  relevant guideline (`docs/api-guideline.md`, `docs/database-guideline.md`, …) — the
  guideline is the day-to-day source of truth, the ADR records the *why*.

## Status values
`Proposed` · `Accepted` · `Deprecated` · `Superseded by NNNN`

## Index
| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-changelog-emoji-sections.md) | Emoji section headers in changelog & release notes | Proposed |
| [0002](0002-two-context-runtime.md) | Single-process, two-context runtime (MQTT + FastAPI) | Proposed |
| [0003](0003-lifespan-lazy-init.md) | Lazy-init the Bridge via FastAPI lifespan | Proposed |
| [0004](0004-api-key-auth-error-envelope.md) | X-API-Key auth + `{detail,error_code}` envelope | Proposed |
| [0005](0005-spoolman-system-of-record.md) | Spoolman = system of record; extra-fields contract | Proposed |
| [0006](0006-mqtt-transport.md) | LAN-MQTT primary, Cloud-MQTT fallback | Proposed |
| [0007](0007-printer-write-paths-gated.md) | Printer write-paths gated behind Dev-Mode flags | Proposed |
| [0008](0008-cloud-import-gated.md) | Bambu Cloud import unconfirmed/gated until capture | Proposed |
| [0009](0009-conventional-commits-semantic-release.md) | Conventional Commits + semantic-release (0.x) | Proposed |
| [0010](0010-governance-hierarchy.md) | Governance hierarchy: ADR > Guideline > Code | Proposed |
| [0011](0011-https-via-reverse-proxy.md) | HTTPS terminated by a reverse proxy | Proposed |

<!-- Add a row per ADR. Further backfill candidates pending clarification (see PR/issues):
  consumption=combined · two-level RFID onboarding · /api/v1 migration · SQLite WAL/migrations ·
  cross-thread locking · build-vs-adopt (openspoolman) · issue-driven workflow.
  0001 two-context architecture (MQTT thread + FastAPI)
  0002 SQLite for persistent bridge state (see database-guideline)
  0003 API versioning + error envelope (see api-guideline)
  0004 Conventional Commits + semantic-release
  0005 Spoolman extra-fields contract
  0006 Bambu Cloud import gated/unconfirmed
-->
