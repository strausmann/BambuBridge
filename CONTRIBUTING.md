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
  lints the commit message with commitlint. `pre-push` runs ruff, the format check and mypy on your
  working tree and lints the commits you are pushing: per pushed ref the range from the remote's
  current commit to yours, or `origin/main..<your commit>` for a branch the remote does not have yet.
  Commits that are already on `origin/main` (merged into your branch) are not linted again.
  Deleting a remote branch checks nothing. Both hooks start containers, so Docker must be running
  (they say so if it is not); the first run downloads the images and dependencies. `HUSKY=0` skips
  both hooks, `git commit --no-verify` skips `commit-msg`, `git push --no-verify` skips `pre-push`.
  (`npm install` on a host with Node activates the same hooks through husky.)
- **`make ci`** runs the same commands with the same thresholds as job `backend` in
  `.github/workflows/ci.yml` (`uv sync --frozen`, ruff, mypy, pytest with branch coverage of at least
  80 %, and at least 90 % for `app/auth/*` and `app/security/*`). Run it before you open or update a
  pull request.
- **Versions come from the workflows.** The Python, uv, Postgres and Node versions are written down
  once, in `.github/workflows/ci.yml` and `commitlint.yml`. The `Makefile` reads them from there
  (`scripts/ci-versions.sh`), so a version bump in a workflow applies to `make ci` without a second
  edit. To try another version, override it for one call: `PYTHON_VERSION=… make ci` (also
  `UV_VERSION`, `POSTGRES_IMAGE`, `NODE_VERSION`). The commands of the `backend` job are repeated in
  the `Makefile`; `backend/tests/unit/test_ci_parity.py` fails when they differ from the workflow or
  when a version can no longer be read from it.
- **Test database.** `make ci` starts the container `bambubridge-ci-postgres` on first use and leaves
  it running for the next run; `make ci-db-stop` removes it together with
  everything in it. It holds test data only and is reached over a Docker network, so no host port is
  needed. To run pytest yourself against it, publish a port: `make ci-db-start CI_DB_PORT=55432`
  (bound to `127.0.0.1`). A container started from another Postgres image than the workflow names
  is replaced automatically. Every test run creates its own databases (`bb_*`) on that server and
  drops them at the end, so several runs can share it. A run that is killed hard (`kill -9`, a
  stopped container) cannot drop its databases; they stay until `make ci-db-stop`.
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

