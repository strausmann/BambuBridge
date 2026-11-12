# Architecture Decision Records (ADRs) — highest authority

This rule loads automatically for every (human or Claude) contributor in this repository.

## What an ADR is
An **Architecture Decision Record** documents a deliberate, binding decision in Nygard format
(**Context → Decision → Consequences**, plus "Options considered"). ADRs live in `docs/decisions/`
(template: `docs/decisions/_template.md`, index: `docs/decisions/README.md`).

## Authority — ADRs rule
On conflict this order applies:
1. **Accepted ADRs** (`docs/decisions/`, status `Accepted`) — **highest authority**
2. README / code conventions / existing code

If code or documentation contradicts an accepted ADR, **that is a defect** — fix it, or write a **new,
superseding ADR**. **Nobody — human or Claude agent — may silently ignore an accepted ADR.**

## Creating
1. Copy `docs/decisions/_template.md` to `docs/decisions/NNNN-short-slug.md` (sequential, zero-padded).
2. Fill in **Status** (`Proposed`), **Date**, **Deciders**, **Context**, **Decision** (positive
   statement "We will …"), **Options considered** (chosen option plus alternatives with pros/cons),
   **Consequences**, **References** (issues/PRs, `file:line`).
3. Add a row to the index table in `docs/decisions/README.md`.

Status values: `Proposed` · `Accepted` · `Deprecated` · `Superseded by NNNN`.
An ADR is `Proposed` until the change ships, then `Accepted` in the same PR.

## Maintaining / changing
- An accepted ADR is **not edited in substance**. A change = a **new** ADR that **supersedes** the old
  one; the old one gets status `Superseded by NNNN`.
- If the decision touches endpoints, fields, database or configuration, update the affected code,
  tests and README in the **same PR**.

## Binding for Claude agents
- **Before** any spec, plan or implementation, read and follow the relevant accepted ADRs.
- The review agents (`network-`, `developer-`, `research-`, `security-reviewer`) check specs and plans
  **against the ADRs** and mark every deviation as **blocking** (`NEEDS-CHANGES`).
- A new direction is **not** implemented silently: propose it first as an ADR (`Proposed`), implement
  after acceptance. How decisions are reached: `.claude/rules/decision-process.md`.
