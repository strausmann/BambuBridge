# 0009 — Conventional Commits + semantic-release; mandatory scope; 0.x/alpha

- **Status:** Proposed
- **Date:** 2026-06-28
- **Deciders:** strausmann
- **Tags:** ci, release

## Context
We want automated, traceable versioning and a generated changelog, without manual version bumps.

## Decision
We will version **exclusively via semantic-release** from **Conventional Commits** (scope
**mandatory**, catalog in `.github/SCOPES.md`); `docs/test/chore/ci/...` are non-releasing. The
project is **0.x / alpha** until a deliberate stable cut. Releases run **weekly (Sunday) or manual
dispatch**, never on push; the `CHANGELOG.md` is generated, not hand-edited.

## Options considered
- **Option A — semantic-release + Conventional Commits, 0.x (chosen):** automated, consistent,
  honest pre-1.0 versioning.
- **Option B — manual SemVer/CHANGELOG:** error-prone, inconsistent.
- **Option C — CalVer:** doesn't express API stability for a library-like service.

## Consequences
- Commit discipline enforced by commitlint (husky + CI).
- First cut is `0.1.0`; 1.0.0 only when deliberately declared stable.

## References
- `.releaserc.json`, `commitlint.config.cjs`, `.github/SCOPES.md`, `.github/workflows/release.yml`;
  release **v0.1.0**; PRs #2/#4/#5. (Changelog **icons**: see ADR 0001.)
