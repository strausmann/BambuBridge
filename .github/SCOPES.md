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
| `mqtt` | LAN/Cloud MQTT ingest, AMS tray parser | `app/mqtt_ingest.py` |
| `spoolman` | Spoolman REST client / sync | `app/spoolman.py` |
| `spoolmandb` | SpoolmanDB import | `app/spoolmandb.py` |
| `db` | SQLite model, migrations | `app/db.py` |
| `consumption` | remain%/per-job reconcile | `app/consumption.py` |
| `jobs` | print-job detection | `app/jobs.py` |
| `tags` | RFID tag lifecycle, compatibility | `app/tags.py` |
| `kcatalog` | k/cali catalog (PA calibration) | `app/kcatalog.py` |
| `cloud` | Bambu Cloud filament import | `app/cloud_library.py` |
| `presets` | Bambu preset generation | `app/preset_gen.py` |
| `labels` | label-printer hub client | `app/labels.py` |
| `ams` | AMS/slot logic, slot-bind flow | `app/main.py` (slot/AMS) |
| `esp32` | ESP32 slot-selector client/firmware | ESP32 + slot APIs |
| `api` | FastAPI app, endpoints, auth, lifespan | `app/main.py`, `app/config.py` |
| `ui` | Tailwind PWA | `web/` |
| `config` | config schema / example | `app/config.py`, `config.example.yaml` |
| `scripts` | helper scripts (capture, build) | `scripts/` |
| `docker` | Dockerfile / compose | `Dockerfile`, `docker-compose.yml` |
| `ci` | GitHub Actions / tooling | `.github/`, lint/release config |
| `docs` | documentation, guidelines, ADRs | `docs/`, `README.md` |
| `deps` | dependency updates | `requirements*.txt`, `package.json` |
| `release` | release plumbing | semantic-release |

## Rules
- **Scope is mandatory**, singular, lowercase. Pick the **most specific** that fits.
- One logical change per commit; one feature/bug = one issue = one branch = one PR.
- Cross-cutting changes: prefer the primary subsystem; use `api` for app-wide wiring.
- New scope needed? Add it here in the same PR (and to `commitlint.config.cjs`).
