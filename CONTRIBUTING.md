# Contributing to BambuBridge

## Workflow at a glance
1. **Every change starts as a GitHub issue** (one issue = one feature/bug). Use the issue templates.
2. **One issue → one branch → one PR.** Branch naming: `feat/<slug>`, `fix/<slug>`, `docs/<slug>`,
   `refactor/<slug>`, `chore/<slug>`.
3. Specs/plans for non-trivial work are reviewed by the project review agents
   (network / developer / research / security — see `.claude/agents/`) **before** implementation,
   to catch deviations from the guidelines early.
4. Implement with tests. Validate locally. Open a PR referencing the issue.

## Source of truth
Binding, in this order of precedence — **ADR > Guideline > Code/README** (see `.claude/rules/adr.md`, `CLAUDE.md` R7):
- `docs/decisions/` — **ADRs have the highest authority** (the *why*; amend by superseding, never by editing).
- `docs/api-guideline.md` — API: `/api/v1`, snake_case, field glossary, error envelope
  `{detail,error_code}`, `X-API-Key` auth, HTTPS.
- `docs/database-guideline.md` — SQLite (WAL, `user_version` migrations, defined tables).
- `CLAUDE.md` — hard rules for any (human or AI) contributor.

If a change alters an endpoint/field/config, update the guideline **+** README **+**
`config.example.yaml` **together** in the same PR.

## Commits — Conventional Commits (enforced)
Format `type(scope): subject`. Scope is **mandatory** — see [`.github/SCOPES.md`](.github/SCOPES.md)
for the catalog and the release-impact table. commitlint runs on `commit-msg` (husky) and in CI.

Examples:
```
feat(api): add X-API-Key dependency on mutating routes
fix(mqtt): guard publish path when broker disconnected
docs(decisions): add ADR 0003 for the error envelope
```

Do **not** add AI attribution (`Co-Authored-By`, `Claude-Session`, "Generated with …") to commits
or PRs — see `CLAUDE.md` R2.

## Local setup & gates
```bash
# Python app
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q
python -m py_compile app/*.py

# Tooling (commit lint, formatting, release) — Node
npm install          # sets up the husky commit-msg hook
npm run format       # prettier (configs/markdown/yaml/json)
```
Containers are tested with Docker on the dev VM (network `traefik-public`); avoid installing
extra dev tooling on the host — run it in containers.

## AI code review (Gemini / Copilot)
Every PR is reviewed by AI bots. **Each finding must be resolved** — either **fixed** (note it on the
thread) or replied to as a **false positive with reasoning**. No finding is left open, and a PR is
merged only when every finding has a status and CI is green. See `.claude/rules/pr-review.md`.

## Releases
Versioning is automated by **semantic-release** from the commit history (`.releaserc.json`):
`feat`→minor, `fix`/`perf`/`refactor`→patch, `!`/`BREAKING CHANGE`→major. Don't bump versions
or edit `CHANGELOG.md` by hand.
