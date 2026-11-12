# Commit Scopes

BambuBridge uses [Conventional Commits](https://www.conventionalcommits.org/) with a
**mandatory, singular, lowercase scope** (most-specific wins). Releases are driven by
[semantic-release](https://semantic-release.gitbook.io/) from these commits.

## Format

```
<type>(<scope>): <subject>
```

- `type` ∈ `feat | fix | perf | refactor | docs | test | build | ci | chore | style | revert`
- `scope` ∈ the table below (exactly one)
- `subject` imperative, lower-case start, no trailing period, header ≤ 120 chars

## Release impact (semantic-release)

| Type | Release |
|------|---------|
| `feat` | minor |
| `fix`, `perf`, `refactor` | patch |
| `docs`, `test`, `build`, `ci`, `chore`, `style` | none |
| any type with `!` or `BREAKING CHANGE:` footer | major |

## Scopes (derived from the actual subsystems)

| Scope | Area | Maps to |
|-------|------|---------|
| `mqtt` | LAN/Cloud MQTT ingest, AMS tray parser | `backend/` |
| `spoolman` | Spoolman REST client / sync | `backend/` |
| `spoolmandb` | SpoolmanDB import | `backend/` |
| `db` | SQLite model, migrations | `backend/` |
| `consumption` | remain%/per-job reconcile | `backend/` |
| `jobs` | print-job detection | `backend/` |
| `tags` | RFID tag lifecycle, compatibility | `backend/` |
| `kcatalog` | k/cali catalog (PA calibration) | `backend/` |
| `cloud` | Bambu Cloud filament import | `backend/` |
| `presets` | Bambu preset generation | `backend/` |
| `labels` | label-printer hub client | `backend/` |
| `ams` | AMS/slot logic, slot-bind flow | `backend/` |
| `esp32` | ESP32 slot-selector client/firmware | slot APIs, ESP32 client |
| `api` | FastAPI app, endpoints, auth, lifespan | `backend/` |
| `ui` | user interface components | `frontend/` |
| `config` | config schema / example | `backend/`, `frontend/` |
| `scripts` | helper scripts (capture, build) | `scripts/` |
| `docker` | Dockerfile / compose | Dockerfiles, compose files |
| `ci` | GitHub Actions / tooling | `.github/`, lint/release config |
| `docs` | documentation, guidelines, ADRs | `docs/`, `README.md` |
| `deps` | dependency updates | `pyproject.toml`, `package.json`, lockfiles |
| `release` | release plumbing | semantic-release |
| `auth` | users, identities, sign-in | `backend/`, `frontend/` |
| `settings` | user and system settings | `backend/`, `frontend/` |
| `providers` | sign-in and cloud providers | `backend/` |
| `events` | printer event stream and handling | `backend/` |
| `pwa` | progressive web app shell, manifest, service worker | `frontend/` |
| `brand` | logo, icons, colour tokens | `docs/brand/` |
| `repo` | repository structure and rules | repository root, `.claude/` |
| `security` | security fixes and hardening | cross-cutting |

## Rules
- **Scope is mandatory**, singular, lowercase. Pick the **most specific** that fits.
- One logical change per commit; one feature/bug = one issue = one branch = one PR.
- Cross-cutting changes: prefer the primary subsystem; use `api` for app-wide wiring.
- New scope needed? Add it here in the same PR (and to `commitlint.config.cjs`).
