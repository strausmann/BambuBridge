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

<!-- ADR numbers are assigned in creation order. The architecture-backfill candidates below get their
     numbers (0002+) when we create them. -->

<!-- Add a row per ADR. Suggested initial ADRs to backfill from the existing concept docs:
  0001 two-context architecture (MQTT thread + FastAPI)
  0002 SQLite for persistent bridge state (see database-guideline)
  0003 API versioning + error envelope (see api-guideline)
  0004 Conventional Commits + semantic-release
  0005 Spoolman extra-fields contract
  0006 Bambu Cloud import gated/unconfirmed
-->
