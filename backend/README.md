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
