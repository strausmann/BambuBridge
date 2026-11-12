"""Container entrypoint: validate the proxy setting, then start uvicorn."""

from __future__ import annotations

import ipaddress
import os

import uvicorn

PORT = 8000


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


def run() -> None:  # pragma: no cover - process start, exercised by the image smoke test
    """Validate configuration and start the server on the fixed port."""
    allowed = validate_forwarded_allow_ips(os.environ.get("FORWARDED_ALLOW_IPS"))
    # Database migrations (alembic upgrade head) are added in a later task.
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",  # noqa: S104 - container listens on all interfaces
        port=PORT,
        proxy_headers=True,
        forwarded_allow_ips=allowed,
        server_header=False,
    )


if __name__ == "__main__":  # pragma: no cover
    run()
