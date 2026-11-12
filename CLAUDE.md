# CLAUDE.md — AI assistant configuration

This file configures **Claude Code** (and other LLM-based tools that read it) for this repository. It is
intentionally short — the project knowledge lives in [`docs/`](docs/). The rules below are **binding (no
exceptions)**.

## Repository layout

| Path | Content |
|------|---------|
| `backend/` | Python service (FastAPI, MQTT ingest, Spoolman sync) |
| `frontend/` | Progressive web app |
| `docs/decisions/` | ADRs — the binding *why* behind every architectural choice |
| `docs/brand/` | Logo, icons, colour tokens |
| `docs/learnings/` | Lessons learned (see R0) |
| `docs/legacy-reference.md` | Where the removed pre-0.2.0 code can still be read in git history |
| `.claude/` | Project agents and rules |

The 0.2.0 rebuild is in progress; `backend/` and `frontend/` arrive with the follow-up tasks of the
foundation plan.

## Hard rules

### R0 — Error culture (top rule)
Every mistake is analysed automatically (root cause), recorded in `docs/learnings/lessons-learned.md`
and answered with a concrete countermeasure (rule / ADR / test / hook). Mistakes are named openly, not
hidden. Details: `.claude/rules/error-handling.md`.

### R1 — Verify first, conclude later; public statements only when proven
Analyse end to end before drawing a conclusion (latest release tag **and** its pinned dependencies,
build/merge/fix dates, the actual code or artefact). Doubly so for anything public or outgoing (issues,
PRs, comments, upstream reports): post only fully proven statements.

### R2 — No AI attribution in version control
Never add `Co-Authored-By`, `Claude-Session`, "Generated with Claude Code" or any other AI self-labelling
to commits, pushes, PRs or issue/PR texts. Plain, factual messages.

### R3 — Use Superpowers
The Superpowers skill set is installed and used by default (brainstorming, planning, TDD workflow, …).
New work follows `.claude/rules/decision-process.md`: clarify to ≥95% before any spec or plan.

### R4 — Issue-driven, one issue per feature/bug
Every change starts as a GitHub issue (templates in `.github/ISSUE_TEMPLATE/`).
**One issue → one branch → one PR.** Branch prefixes: `feat/ fix/ docs/ refactor/ chore/`.

### R5 — Reviewers check specs and plans before implementation
Before a spec or plan is finalised, the project agents in `.claude/agents/` (network-, developer-,
research-, security-reviewer) review it, against the ADRs. Two or three rounds if in doubt.

### R6 — Conventional Commits + semantic-release
Commits are `type(scope): subject` with a **mandatory scope** (catalogue: `.github/SCOPES.md`). Versions
come from semantic-release; no manual version or changelog edits. Commit messages carry no emoji; the
generated changelog sections do (ADR to be recorded with the release tooling).

### R7 — ADRs are the top authority
Accepted ADRs in `docs/decisions/` outrank everything else; procedure in `.claude/rules/adr.md`.
Precedence on conflict: **ADR > code/README**. A new direction needs a new (superseding) ADR, never a
silent deviation.

### R8 — Appearance comes from `docs/brand/`
Logo, icons and colours come exclusively from [`docs/brand/`](docs/brand/README.md) (mark "Drehscheibe",
tokens in `docs/brand/tokens.css`). Do not invent colours, use no Bambu Lab brand elements, no Bambu
green. BambuBridge is not a product of Bambu Lab.

## Things to propose, not do silently
- A new dependency — justify it in the PR description.
- An architecture change — propose it as an ADR PR before implementing.

## Privacy
Never commit internal addresses, hostnames, tokens, serial numbers or LAN access codes. Use placeholders.
