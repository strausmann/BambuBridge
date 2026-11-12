"""Container entrypoint: validate the proxy setting, then start uvicorn."""

from __future__ import annotations

import ipaddress
import os
from typing import Any

import uvicorn
from alembic import command

from app.migrations import make_alembic_config

PORT = 8000
MAX_HEADER_BYTES = 64 * 1024


def validate_forwarded_allow_ips(value: str | None) -> str:
    """Return ``value`` if it is exactly one IP address, otherwise exit.

    ``*``, ranges and lists are refused: trusting proxy headers from anywhere
    would let any client spoof its address.
    """
    candidate = (value or "").strip()
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        raise SystemExit(
            "FORWARDED_ALLOW_IPS must be exactly one IP address of the reverse proxy "
            "(not '*', a range or a list)"
        ) from None
    return candidate


def server_options(forwarded_allow_ips: str) -> dict[str, Any]:
    """uvicorn options besides the application, host and port.

    The h11 protocol with ``h11_max_incomplete_event_size`` bounds the header block and
    chunked trailers to ``MAX_HEADER_BYTES``: a request that grows past it gets ``400`` and
    the connection is closed. (httptools, uvicorn's default when installed, has no such
    bound; the request body is limited separately, see ``app.web.body_limit``.)
    """
    return {
        "http": "h11",
        "h11_max_incomplete_event_size": MAX_HEADER_BYTES,
        "proxy_headers": True,
        "forwarded_allow_ips": forwarded_allow_ips,
        "server_header": False,
    }


def run() -> None:
    """Validate configuration, migrate the database to head, start the server."""
    allowed = validate_forwarded_allow_ips(os.environ.get("FORWARDED_ALLOW_IPS"))
    # URL comes from BAMBUBRIDGE_DATABASE_URL (see app/migrations/env.py); failure stops start.
    command.upgrade(make_alembic_config(), "head")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",  # noqa: S104 - container listens on all interfaces
        port=PORT,
        **server_options(allowed),
    )


if __name__ == "__main__":  # pragma: no cover
    run()
