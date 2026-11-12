# Contributing to BambuBridge

## Workflow at a glance
1. **Every change starts as a GitHub issue** (one issue = one feature/bug). Use the issue templates.
2. **One issue → one branch → one PR.** Branch naming: `feat/<slug>`, `fix/<slug>`, `docs/<slug>`,
   `refactor/<slug>`, `chore/<slug>`.
3. Specs/plans for non-trivial work are reviewed by the project review agents
   (network / developer / research / security — see `.claude/agents/`) **before** implementation,
   to catch deviations from the ADRs early.
4. Implement with tests. Validate locally. Open a PR referencing the issue.

## Source of truth
Binding, in this order of precedence — **ADR > code/README** (see `.claude/rules/adr.md`, `CLAUDE.md` R7):
- `docs/decisions/` — **ADRs have the highest authority** (the *why*; amend by superseding, never by editing).
- `CLAUDE.md` — hard rules for any (human or AI) contributor.

If a change alters an endpoint, field or configuration, update the affected code, tests and README
**together** in the same PR.

## Commits — Conventional Commits (enforced)
Format `type(scope): subject`. Scope is **mandatory** — see [`.github/SCOPES.md`](.github/SCOPES.md)
for the catalog and the release-impact table. commitlint runs on `commit-msg` (after `make hooks`, see below) and in CI.

Examples:
```
feat(api): add X-API-Key dependency on mutating routes
fix(mqtt): guard publish path when broker disconnected
docs(decisions): add ADR 0003 for the error envelope
```

Do **not** add AI attribution (`Co-Authored-By`, `Claude-Session`, "Generated with …") to commits
or PRs — see `CLAUDE.md` R2.

## Local setup & gates
Everything runs in containers that match CI; nothing is installed on the host. You need **Docker**,
**GNU make** and **git** — no Python, uv or Node on the host.

```bash
make hooks      # once per clone: activates the git hooks (sets core.hooksPath to .husky)
make ci-fast    # ruff check, ruff format --check, mypy, commitlint for origin/main..HEAD - no database
make ci         # the steps of CI job "backend", against a local test Postgres
make ci-db-stop # stop the test Postgres
```

- **Hooks.** A fresh clone has no active hooks until `make hooks` has run. After that, `commit-msg`
  lints the commit message with commitlint and `pre-push` runs `make ci-fast`. Both start containers,
  so Docker must be running; the first run downloads the images and dependencies. `HUSKY=0` skips
  both hooks, `git push --no-verify` skips the pre-push check. (`npm install` on a host with Node
  activates the same hooks through husky.)
- **`make ci`** runs the same commands with the same thresholds as job `backend` in
  `.github/workflows/ci.yml` (`uv sync --frozen`, ruff, mypy, pytest with branch coverage of at least
  80 %, and at least 90 % for `app/auth/*` and `app/security/*`). Run it before you open or update a
  pull request. When that job changes, change the `ci` target in the `Makefile` in the same PR.
- **Test database.** `make ci` starts the container `bambubridge-ci-postgres` (`postgres:18.6-trixie`,
  published on `127.0.0.1:55432`, override with `CI_DB_PORT=…`) on first use and leaves it running for
  the next run; `make ci-db-stop` removes it. It holds test data only. Every test run creates its own
  databases on that server and drops them at the end, so several runs can share it.
- **Caches.** uv downloads, the virtual environment and the npm cache live in the gitignored `.cache/`
  of your clone; delete the directory to start from scratch.
- **Extra pytest arguments:** `make ci PYTEST_ARGS="-x -k tokens"`. For a quicker local run use
  `make ci PYTEST_ARGS="-n auto"` (pytest-xdist; each worker gets its own database). CI runs the suite
  without `-n`, and so does plain `make ci`.

The gates for `frontend/` (Node) are documented next to the code once that directory exists.

## AI code review (Gemini / Copilot)
Every PR is reviewed by AI bots. **Each finding must be resolved** — either **fixed** (note it on the
thread) or replied to as a **false positive with reasoning**. No finding is left open, and a PR is
merged only when every finding has a status and CI is green. See `.claude/rules/pr-review.md`.

## Releases
Versioning is automated by **semantic-release** from the commit history (`.releaserc.json`):
`feat`→minor, `fix`/`perf`/`refactor`→patch, `!`/`BREAKING CHANGE`→major. Don't bump versions
or edit `CHANGELOG.md` by hand.

## License and CLA

The project is licensed under AGPL-3.0-or-later (see [LICENSE](LICENSE)). Contributions require agreement to the
[Contributor License Agreement](CLA.md): tick the CLA checkbox in the pull request template. If the CLA assistant
is enabled for the repository it additionally asks you to sign once on the first pull request.

