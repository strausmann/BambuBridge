# Architecture Decision Records (ADRs)

Binding decisions for BambuBridge live here, one file per decision, in the
[Nygard format](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).

## Rules
- **One file per decision**, named `NNNN-short-slug.md` (zero-padded, sequential).
- A file **stays once written**. To change a decision, write a **new** ADR that
  supersedes the old one, and set the old one's status to `Superseded by NNNN`.
- Copy [`_template.md`](_template.md) for new ADRs.
- Decisions that change project direction or conventions must also be reflected in the
  affected code, tests and README in the same PR — the ADR records the *why*.

## Status values
`Proposed` · `Accepted` · `Deprecated` · `Superseded by NNNN`

## Index
| ADR | Title | Status |
|-----|-------|--------|
| _none yet_ | | |

<!-- Add a row per ADR. -->
