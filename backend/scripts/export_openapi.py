"""Print the backend's OpenAPI document to stdout (``pnpm gen:api`` in ``frontend/``).

Needs no running server, no database and no real settings: the app factory gets obviously
fake placeholder settings (the engine connects lazily), and the schema is built from the
route table.

    uv run python scripts/export_openapi.py > ../frontend/openapi.json
"""

from __future__ import annotations

import base64
import json
import sys

from pydantic import AnyHttpUrl, SecretStr

from app.config import Settings
from app.main import create_app


def placeholder_settings() -> Settings:
    """Settings that satisfy validation and name nothing real."""
    return Settings(
        database_url=SecretStr("postgresql+asyncpg://export:export@localhost:1/export"),
        secret_key=SecretStr(
            base64.urlsafe_b64encode(b"openapi-export-only-key-00000000").decode()
        ),
        public_url=AnyHttpUrl("http://localhost:8000"),
        bootstrap_admin_key=SecretStr(""),
    )


def render() -> str:
    """The OpenAPI document as stable JSON text (sorted keys, trailing newline)."""
    schema = create_app(placeholder_settings()).openapi()
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    sys.stdout.write(render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
