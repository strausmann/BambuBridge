# 0001 — Emoji section headers in changelog & release notes

- **Status:** Proposed
- **Date:** 2026-06-28
- **Deciders:** strausmann
- **Tags:** release, docs

## Context
Changelog and GitHub release-note sections were plain text. We want consistent, scannable **icons**
across all projects' changelogs and release notes (a stated, confirmed preference).

## Decision
We will prefix changelog/release-note **section headers with a fixed emoji set**, configured via the
conventionalcommits preset (`presetConfig.types`) in semantic-release (and, for projects that keep a
manual Keep-a-Changelog, in the category headers).

## Options considered
- **Option A — emoji via `presetConfig.types` (chosen):** consistent, low-effort, applies to the
  auto-generated changelog **and** the GitHub release notes; no change to commit conventions.
- **Option B — gitmoji-style commit prefixes:** would change the commit message convention; rejected
  (keeps Conventional Commits clean and tooling-friendly).
- **Option C — no icons:** rejected (explicit preference for icons).

## Consequences
- Section mapping: `feat` ✨ Features · `fix` 🐛 Bug Fixes · `perf` ⚡ Performance · `refactor`
  ♻️ Refactoring · `docs` 📝 Documentation · `build`/`ci` 🔧 · `revert` ⏪ Reverts; breaking changes
  use the preset's ⚠ BREAKING section. `test`/`style`/`chore` stay hidden.
- (Manual Keep-a-Changelog projects use the analogous category icons: ✨ Added · ♻️ Changed ·
  ⚠️ Deprecated · 🗑️ Removed · 🐛 Fixed · 🔒 Security.)
- Already-released entries are **not** rewritten; the convention applies to future releases.
- Same convention is adopted in all our projects for consistency.

## References
- semantic-release `conventional-changelog-conventionalcommits` `presetConfig.types`.
- `.releaserc.json` (this change); confirmed in chat 2026-06-28.
