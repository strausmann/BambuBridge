"""Pluggable sign-in providers (see ``base`` for the interface, ``registry`` for selection).

Importing this package registers the built-in providers. 0.2.0 ships one: the trusted
Pangolin headers (``pangolin_header``).
"""

from app.auth.identity import registry
from app.auth.identity.base import Identity, IdentityProvider
from app.auth.identity.pangolin_header import PangolinHeaderProvider

registry.register(PangolinHeaderProvider())

__all__ = ["Identity", "IdentityProvider", "PangolinHeaderProvider", "registry"]
