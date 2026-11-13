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
- **Input checks:** `emit` refuses, with a `ValueError` and before it sends anything to the
  database, what PostgreSQL would refuse or what is beyond the limits: a payload that is not
  a dict of JSON values, a type name of more than 200 characters, a `schema_version`
  outside 1 to 2147483647, a NUL or surrogate character in any string, `NaN` or infinite
  numbers, more than 32 levels of nesting, more than 64 KiB of JSON text; a `dedup_key` that
  is empty, longer than 200 characters or holds such a character; a source or correlation id
  that is not a `UUID` (the text form is not taken). The caller's transaction stays usable,
  and the messages never quote a value. Because the database never sees such input, no
  fragment of a payload ends up in the PostgreSQL server log through a parse error.
- **Duplicates:** with a `dedup_key`, a second event of the same source and the same type
  with the same key inside `events.dedup_window_seconds` (runtime setting, default 600, `0`
  switches it off) is dropped and `emit` returns `None`. The window starts at the earlier
  event. A transaction that stays open for longer than the window after its `emit` therefore
  lets a duplicate through that waited for it.
- **Order per source:** `emit` holds an advisory lock on the source until the caller's
  transaction ends, so the events of one source are stored in commit order. Emit late in
  the transaction and commit soon after: a second `emit` for the same source waits for the
  first one, for at most 5 seconds. Then it raises `SourceBusyError`, and its transaction
  has to be rolled back.
- **Delivery:** a worker takes deliveries with `outbox.claim(session, subscriber, worker_id)`
  (`FOR UPDATE SKIP LOCKED`, at most 1000 per call) and commits. From then on the batch is
  leased to that worker for 5 minutes and no other claim returns it. The worker processes
  the batch, calls `outbox.complete` or `outbox.fail` with its worker id, and commits again.
  Both change only deliveries the worker still holds, so a late result cannot overwrite
  the result of a worker that took the delivery over. A failed delivery is retried after 2,
  4, 8 ... seconds. A lease that runs out without a result (the worker died) counts as an
  attempt as well, and the delivery goes to the next claim. After the tenth attempt a
  delivery is set to `failed`. A worker that dies inside `claim` or before that first commit
  leaves no lease and is not counted.
  Delivery is **at least once**: a worker that dies after its side effect and before the
  commit of `complete` makes the next worker run the handler again, so handlers must be
  idempotent. A lease is not renewed, on purpose. Size a batch so that it is finished well
  inside the 5 minutes: what is left after that is taken over by another worker of the same
  subscriber, runs twice and counts an attempt. With slow handlers or a small container use
  a small `limit`.
  Keep transactions short (claim, commit, process, complete or fail, commit): while one is
  open, no new monthly partition can be created.
- **Partitions:** `events` and `communication_log` are partitioned by month
  (`events_y2026m12`, `communication_log_y2026m12`). The server creates
  the partitions for the current and the next two months at startup and every day at
  00:05 UTC. There is no default partition. Creating one needs the table exclusively for a
  moment; if a long transaction still uses it, the server gives up after 3 seconds and
  tries again a minute later, so writers are never held up for longer than that. If
  another object already carries the name of a partition, the server logs an error on every
  run and leaves that month out until the object is removed. Such a run still counts as
  successful: for now the log line (`cannot create partition ...`) is the only place where
  this shows, it is not part of `/readiness` yet.

## Communication log

What a provider instance sends and receives is written to `communication_log` by
`CommunicationRecorder` (`app/events/communication.py`), and only by it. Provider code uses
`record_isolated(session_factory, ...)`: it writes the row in a short transaction of its own
and swallows a database error (for example a missing partition), with one warning that
names the error class and SQLSTATE only, so a failed log entry never fails the work it
describes. `record(session, ...)` adds the row to the caller's transaction instead and does
not commit; a database error then aborts that transaction. Use it only where the entry has
to be atomic with other work.

Every stored part (address, headers, both bodies, the error text) goes through three steps,
in this order:

1. **Make it storable.** NUL characters are removed and surrogate code points replaced by
   U+FFFD; nothing a peer sends makes the log fail. A body given as bytes that is not UTF-8
   text, or contains a NUL byte, is stored as `<binary N bytes>`. Header bytes are read as
   UTF-8 when they are valid UTF-8, otherwise as ISO 8859-1.
2. **Mask** (`app/security/masking.py`); `***` takes the place of
   - the value of a header, JSON field, query or form parameter named `authorization`,
     `cookie`, `set-cookie` or `x-bambubridge-key`, or whose name contains `token`,
     `secret`, `passw`, `pwd`, `key`, `auth` (not `author`), `cookie`, `credential`,
     `session`, `sessid`, `signature`, `access_code` (also `accessCode`, `access-code`),
     `passcode`, `passphrase`, `pincode`, `totp`, `jwt`, `ticket`, `assertion`, `psk`,
     `csrf`, `xsrf` or `samlresponse`, or has `pass`, `pw`, `pin`, `otp`, `sig` or `sid` as
     a word of its own (`user_pass`, `userPW`, `pin_code`), in any case;
   - every field named like the last segment of a path the provider schema marks with
     `"x-secret": true` (`secret_paths_from_schema`), wherever it stands;
   - every occurrence of a known secret value of 8 characters or more (surrounding white
     space removed) in any spelling an encoder writes: each character as itself or escaped
     (percent escapes in either case, `\uXXXX`, `\xNN`, `\/`, `+` for a space ...), the
     Python `repr` spellings, and base64 or base64url, also inside a longer base64 value and
     wrapped over several lines;
   - the user information in `scheme://user:password@host` up to the last `@` (the whole of
     it when there is no colon), and the credential after `Bearer` or `Basic`.

   A JSON body is masked on its parsed values (after a byte order mark); an object that
   repeats a name is rewritten with the repeats numbered (`name#2`), so no parser can pick
   another value. Any other text is searched at every position for `"name": value` and
   `'name': value`, `name=value` and `name = value` (quoted, or bare up to `&` or white
   space), `name: value` (the rest of the line, as in `Authorization: Token x` or
   `Cookie: a=1; sid=x`), `--name value`, and multipart form fields
   (`Content-Disposition: form-data; name="password"`), also inside the quoted value of
   another name; and once more in the percent-decoded text (decoded up to three times), which
   is then the text stored if that finds anything.
3. **Cut.** Each body is stored up to 8192 bytes of UTF-8 (never cut inside a character),
   the address up to 2048 characters, the error up to 2000, at most 100 headers with values
   up to 2048 characters. Any cut sets `truncated`.

Masking comes before cutting: a secret across the 8192-byte limit would otherwise be stored
as a fragment that no rule recognises. Only the first 65536 characters of a text are looked
at, and 65536 characters of the headers of one side in all; that first cut never goes
through a known secret.

The limits of masking: it prefers hiding too much (a field called `monkey` is masked), it
cannot find a secret that has neither a telling name, nor a schema mark, nor a known value,
and it does not recognise a known value that was transformed in another way (hashed,
encrypted, escaped in two different ways at once). A provider has to pass all the secrets of
its instance as `known_secrets` (strings or UTF-8 bytes; anything else is refused).
`record` writes nothing to the application log.

## Retention

Events are kept for `retention.events_days` (default 90), communication log entries for
`retention.communication_days` (default 30); both are runtime settings (1 to 3650). The
server applies them 15 minutes after startup and every day at 00:15 UTC, and reads the two
values from the database for every run, so a change needs no restart. Each run logs its two
cut-offs before it removes anything.

The periods are counted back from the database clock. If the host clock differs from it by
more than five minutes the run is skipped with a warning (`retention skipped: ...`): a host
clock far ahead would otherwise delete what is current. A partition whose range holds or
follows the database's present moment is never dropped.

A run deletes the rows older than the period in the month the cut-off falls into and drops
the monthly partitions that lie entirely before it. Outbox deliveries of events older than
the period are deleted with them, except pending ones a worker holds under a lease that has
not run out; those go with a later run. Finished deliveries are counted in the info line,
pending ones that were deleted get a warning of their own. Dropping a partition needs the
table exclusively for a moment: as for creating one, the server gives up after 3 seconds if
a long transaction still uses the table, logs `retention failed (... SQLSTATE 55P03)` and
tries again after 1, 5 and then every 15 minutes; other failures are retried after a
minute. Rows that were already deleted stay deleted. Only partitions with the server's own
names are dropped; a partition attached under another name is left alone.

A shorter period takes effect with the next run and cannot be undone: what is older is
removed.

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
