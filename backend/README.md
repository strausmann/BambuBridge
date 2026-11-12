# BambuBridge backend

FastAPI service. Run the checks with `uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest`.

## Tests need PostgreSQL

The suite requires `BAMBUBRIDGE_TEST_DATABASE_URL` and aborts without it. It creates a database
`bb_test_<pid>` per run, migrates it with `alembic upgrade head` and truncates all tables before
each test. Locally:

```bash
docker run -d --rm -p 55432:5432 -e POSTGRES_PASSWORD=test postgres:18.6-trixie
export BAMBUBRIDGE_TEST_DATABASE_URL=postgresql+asyncpg://postgres:test@localhost:55432/postgres
```

Migrations: `uv run alembic upgrade head` and `uv run alembic check` (reads `BAMBUBRIDGE_DATABASE_URL`).
The container entrypoint runs `alembic upgrade head` before it starts the server.

## Rotating the secret key

Secrets in the database (`app_settings.secret_token`) are sealed with `BAMBUBRIDGE_SECRET_KEY`.
To change the key:

1. **Stop the server.** A running server holds the old key; after the rotation it would report
   every secret as undecryptable until it is restarted with the new key.
2. Set the new value as `BAMBUBRIDGE_SECRET_KEY` and the previous one as
   `BAMBUBRIDGE_SECRET_KEY_OLD`, then run `bambubridge secrets rotate`. All secrets are
   re-encrypted in one transaction (nothing changes if one cannot be opened), and the rotated
   settings are announced on the settings channel when it commits.
3. Remove `BAMBUBRIDGE_SECRET_KEY_OLD` and start the server with the new key.

The old key is read by this command only, never by the server. Without the old key the command
exits with status 2.

## API tokens

Requests authenticate with the header `X-BambuBridge-Key: bb_pat_…` (not `Authorization`, so a
reverse proxy's basic-auth bypass can sit next to it). Scopes are `read` < `operate` < `admin`;
a token never acts above its owner's role, and a disabled owner invalidates all of their tokens.
Only a 16-character prefix and a bcrypt hash are stored; the plaintext is shown once.

The first admin token comes from one of two places:

- **Bootstrap:** with `BAMBUBRIDGE_BOOTSTRAP_ADMIN_KEY` set (at least 32 characters),
  `POST /api/v1/admin/api-keys` with the header `X-BambuBridge-Bootstrap: <key>` and the body
  `{"name": "…", "scope": "admin"}` creates exactly one admin token. As long as an enabled,
  unexpired admin token of an enabled admin user exists, bootstrap answers 403
  `bootstrap_closed`.
- **CLI:** `bambubridge admin create-key --scope admin --name NAME` (reads
  `BAMBUBRIDGE_DATABASE_URL`) prints the token once on stdout.

Each token has a sliding 60-second rate limit (`rate_limit_per_minute`, default 60); excess
requests get 429 with `Retry-After`. The counter lives in process memory: it is per process
and starts fresh after a restart.

Errors are problem details (`application/problem+json`) with a stable `error_code`, for example
`not_authenticated`, `invalid_token`, `token_expired`, `token_disabled`, `owner_disabled`,
`insufficient_scope`, `rate_limited`, `invalid_bootstrap_key`, `bootstrap_closed` and
`database_unavailable`.
