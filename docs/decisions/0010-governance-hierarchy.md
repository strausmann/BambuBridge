# 0010 — Governance hierarchy: ADR > Guideline > Code; ADRs immutable after accept

- **Status:** Proposed
- **Date:** 2026-06-28
- **Deciders:** strausmann
- **Tags:** docs

## Context
Multiple sources (ADRs, guidelines, code, README) can describe how the project works; conflicts need
a defined precedence, and decisions must not drift silently.

## Decision
We will treat **accepted ADRs as the top authority** over guidelines and code (**ADR > Guideline >
Code/README**). A decision change requires a **new, superseding ADR** (old → `Superseded by NNNN`),
plus the matching guideline/README/config update in the same PR. No silent drift.

## Options considered
- **Option A — ADR-top hierarchy, supersede-don't-edit (chosen):** clear authority, traceable history.
- **Option B — guidelines as top authority:** loses the "why" + decision history.

## Consequences
- Guidelines are the operative form of ADR decisions, not a replacement.
- Review agents flag ADR deviations as blocking.

## References
- `CLAUDE.md` R7; `.claude/rules/adr.md`; `docs/decisions/README.md`; PR #2.
