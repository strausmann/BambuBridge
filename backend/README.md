# BambuBridge backend

FastAPI service. Run the checks with `uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest`.

## Tests need PostgreSQL

The suite requires `BAMBUBRIDGE_TEST_DATABASE_URL` and aborts without it. It creates its own
database per run (`bb_test_…`), migrates it with `alembic upgrade head` and truncates all tables
before each test. Tokens are hashed with the cheapest bcrypt cost in tests; tests marked
`production_bcrypt_cost` pin the shipped cost of 12. From the repository root, `make ci` runs the
whole chain in containers (see `CONTRIBUTING.md`). `pytest -n auto` runs the tests in parallel, one
database per worker. By hand:

```bash
docker run -d --rm -p 55432:5432 -e POSTGRES_PASSWORD=test postgres:18.6-trixie
export BAMBUBRIDGE_TEST_DATABASE_URL=postgresql+asyncpg://postgres:test@localhost:55432/postgres
```

Migrations: `uv run alembic upgrade head` and `uv run alembic check` (reads `BAMBUBRIDGE_DATABASE_URL`).
The container entrypoint runs `alembic upgrade head` before it starts the server.

## Rotating the secret key

Secrets in the database (`app_settings.secret_token`) are sealed with `BAMBUBRIDGE_SECRET_KEY`.
The key is a master key and is never used directly: AES-GCM for stored secrets, the CSRF tokens
and the session binding each use their own sub-key derived with HKDF-SHA256. The key id stored
next to a sealed secret identifies the master key, so rotation works on the master key alone.
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
  `{"name": "…", "scope": "admin"}` creates exactly one admin token for the user `admin`. As
  long as an enabled, unexpired token with scope `admin` exists, bootstrap answers 403
  `bootstrap_closed`. If the user `admin` is disabled or no longer has the role `admin`,
  bootstrap refuses with `bootstrap_owner_disabled` / `bootstrap_owner_not_admin` instead of
  issuing a token that could not be used. Each client address may present five wrong
  bootstrap keys per minute; after that it gets 429 without the key being compared, also for
  the right key. While the variable is set and bootstrap is open, the server logs a warning at
  start: create the first admin token, then remove `BAMBUBRIDGE_BOOTSTRAP_ADMIN_KEY`.
- **CLI:** `bambubridge admin create-key --scope admin --name NAME` (reads
  `BAMBUBRIDGE_DATABASE_URL`) prints the token once on stdout.

Each token has a sliding 60-second rate limit (`rate_limit_per_minute`, default 60); excess
requests get 429 with `Retry-After`. Failed checks (wrong token bodies) have a separate
budget per presented prefix (10 per minute, then 429; the same for unknown prefixes, so the
answer does not reveal whether a prefix exists). The budget changes the status code of a
failed check, not its cost: every attempt is checked with bcrypt, so a correct token is always
accepted, even while its prefix is under attack. In addition each client address has a budget of
30 failed checks per minute: an address over it gets 429 before any bcrypt work, for every
prefix alike. This only throttles the guessing address; a correct token from any other address,
or from the same address while under budget, is still checked and accepted, and a token verified
in the last five minutes is accepted even from an address over budget. IPv4 clients are counted
per address (IPv4-mapped IPv6 as IPv4), IPv6 clients per /64 network. A request without a usable
client address skips this per-client check (the per-prefix budget still applies), so such
clients never share one bucket. The client address is the forwarded one, trusted only from the
single proxy address in `FORWARDED_ALLOW_IPS`. If that setting does not match your proxy, every
client appears as the proxy's own address and all of them share one budget: one guesser then
throttles everyone, so check it when all clients get 429 at once.
Browser sign-ins (`POST /api/v1/auth/session`, `GET /auth/continue`) are limited per client address
by the setting `auth.sign_in_limit_per_minute` (clients without a usable address share one
sign-in bucket). At most four bcrypt checks run at once; further
requests queue. Protecting CPU against request floods is the job of the reverse proxy in front of
BambuBridge. Request bodies are limited to 64 KiB: a larger `Content-Length`, or a chunked body that
grows past it, is refused with 413 before any handler or credential check runs. The request
header block and chunked trailers are limited to 64 KiB by the HTTP server (larger: 400 and the
connection is closed). The counters live in process memory: they are per process and start fresh
after a restart.
`last_used_at` is updated at most once per minute.

Errors are problem details (`application/problem+json`) with a stable `error_code`, for example
`not_authenticated`, `invalid_token`, `token_expired`, `token_disabled`, `owner_disabled`,
`insufficient_scope`, `rate_limited`, `invalid_bootstrap_key`, `bootstrap_closed`,
`validation_failed` (field locations and messages only, never the submitted values),
`not_found`, `method_not_allowed`, `payload_too_large` (request body over 64 KiB), `database_unavailable` (the database cannot be reached)
and `internal_error` (anything else; details only in the server log).

## Browser sessions

A browser signs in with a token (`POST /api/v1/auth/session`) or through the trusted SSO header
(`GET /auth/continue`). Sessions last 12 hours. Each user has at most 20 active sessions per
credential: one API token is one credential, and all identity-provider (SSO) sign-ins of the user
together are another. A new sign-in over the cap revokes the oldest session of the same
credential only, so a token, even one with scope `read`, can never sign the operator out of a
session opened with another token or with SSO. In total a user can hold at most
20 × (number of the user's API tokens + 1) active sessions.

`GET /auth/continue` without a valid session cookie opens a new SSO session each time. The
session cookie is `SameSite=Strict`, so a link from another site that leads a signed-in browser
there also opens a new session. This is accepted: only the session token's hash is stored, so an
existing session cannot be handed out again; new sessions count against
`auth.sign_in_limit_per_minute`; and because the cap is per credential, the churn only rotates
that user's own SSO sessions.

## Events and the outbox

Everything that happens is written as an event (`app/events/`). `EventService.emit` stores
the event and one delivery per registered subscriber in the caller's transaction, so a
subscriber never sees an event whose transaction was rolled back and never misses one that
was committed. `emit` does not commit; the caller does.

- **Type names** follow `(account|inventory|integration|display).<subject>.<action>` in
  lower case, for example `integration.demo.tick`. Other names are rejected.
- **Duplicates:** with a `dedup_key`, a second event of the same source with the same key
  inside `events.dedup_window_seconds` (runtime setting, default 600, `0` switches it off)
  is dropped and `emit` returns `None`.
- **Order per source:** `emit` holds an advisory lock on the source until the caller's
  transaction ends, so the events of one source are stored in commit order. Keep such
  transactions short.
- **Delivery:** subscribers take their deliveries with `outbox.claim` (`FOR UPDATE SKIP
  LOCKED`, so several workers never get the same one), then call `outbox.complete` or
  `outbox.fail`. A failed delivery is retried after 2, 4, 8 ... seconds and is set to
  `failed` after the tenth attempt.
  Keep the claim transaction short (claim a batch, hand it on, commit): while it is open,
  no new monthly partition can be created.
- **Partitions:** `events` is partitioned by month (`events_y2026m12`). The server creates
  the partitions for the current and the next two months at startup and every day at
  00:05 UTC. There is no default partition. Creating one needs the table exclusively for a
  moment; if a long transaction still uses it, the server gives up after 3 seconds and
  tries again a minute later, so writers are never held up for longer than that.

## Health checks

`GET /healthz` needs no credentials and answers 200 while the process runs. `GET /readiness`
needs scope `read` and checks the database and the settings listener: 200 when both are up,
otherwise 503 naming the part that is down. The credential check is bounded to 3 seconds; under a
flood of invalid tokens it can run out of that time, and `/readiness` then answers 503 with
`database: unavailable`. It never answers 200 to a request without a valid credential. `HEAD` is
answered wherever `GET` is, with the same status and headers and no body.

## Reverse proxy

BambuBridge does not set `Strict-Transport-Security`. HSTS belongs to the TLS-terminating
reverse proxy in front of it (Traefik, Pangolin): set it there for the public host name.
