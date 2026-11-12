"""Command line interface: ``bambubridge secrets rotate`` and ``admin create-key``."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence

from sqlalchemy.exc import SQLAlchemyError

from app.auth.scopes import SCOPES, Scope
from app.build_info import VERSION
from app.db.engine import make_engine
from app.db.session import make_session_factory
from app.repositories import api_keys as api_keys_repo
from app.repositories import users as users_repo
from app.security.keys import decode_secret_key
from app.security.rotation import ReencryptStep, RotationError, rotate_secrets
from app.settings_store.rotation import reencrypt_app_settings

EXIT_USAGE = 2

# Every table that holds sealed secrets contributes one step; all run in one transaction.
REENCRYPT_STEPS: list[ReencryptStep] = [reencrypt_app_settings]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bambubridge")
    parser.add_argument("--version", action="version", version=f"bambubridge {VERSION}")
    commands = parser.add_subparsers(dest="command")
    secrets = commands.add_parser("secrets", help="manage stored secrets")
    secrets_commands = secrets.add_subparsers(dest="secrets_command", required=True)
    secrets_commands.add_parser(
        "rotate",
        help="re-encrypt all stored secrets from the old to the new secret key",
    )
    admin = commands.add_parser("admin", help="administration")
    admin_commands = admin.add_subparsers(dest="admin_command", required=True)
    create_key = admin_commands.add_parser(
        "create-key",
        help="create an API token for the admin user and print it once",
    )
    create_key.add_argument("--scope", required=True, choices=SCOPES)
    create_key.add_argument("--name", required=True)
    return parser


def _fail(message: str, code: int) -> int:
    sys.stderr.write(f"error: {message}\n")
    return code


def _rotate() -> int:
    """Read the keys from the environment (never from arguments, which show up in ``ps``)."""
    old_text = os.environ.get("BAMBUBRIDGE_SECRET_KEY_OLD", "").strip()
    new_text = os.environ.get("BAMBUBRIDGE_SECRET_KEY", "").strip()
    url = os.environ.get("BAMBUBRIDGE_DATABASE_URL", "").strip()
    if not old_text:
        return _fail("BAMBUBRIDGE_SECRET_KEY_OLD is not set", EXIT_USAGE)
    if not new_text:
        return _fail("BAMBUBRIDGE_SECRET_KEY is not set", EXIT_USAGE)
    if not url:
        return _fail("BAMBUBRIDGE_DATABASE_URL is not set", EXIT_USAGE)
    try:
        old_key = decode_secret_key(old_text, name="BAMBUBRIDGE_SECRET_KEY_OLD")
        new_key = decode_secret_key(new_text, name="BAMBUBRIDGE_SECRET_KEY")
    except ValueError as exc:
        return _fail(str(exc), EXIT_USAGE)
    if old_key == new_key:
        return _fail("the old and the new key are identical; nothing to rotate", EXIT_USAGE)

    async def run() -> int:
        engine = make_engine(url)
        try:
            return await rotate_secrets(engine, REENCRYPT_STEPS, old_key=old_key, new_key=new_key)
        finally:
            await engine.dispose()

    try:
        count = asyncio.run(run())
    except RotationError as exc:
        return _fail(f"{exc}; nothing was changed", 1)
    except (OSError, SQLAlchemyError) as exc:
        return _fail(f"database error ({type(exc).__name__}); nothing was changed", 1)
    sys.stdout.write(f"re-encrypted {count} secrets\n")
    return 0


_NAME_MAX = 100


def _create_key(scope: Scope, name: str) -> int:
    """Create a token owned by the user ``admin``; the plaintext goes to stdout once."""
    url = os.environ.get("BAMBUBRIDGE_DATABASE_URL", "").strip()
    if not url:
        return _fail("BAMBUBRIDGE_DATABASE_URL is not set", EXIT_USAGE)
    name = name.strip()
    if not name or len(name) > _NAME_MAX:
        return _fail(f"--name must be 1 to {_NAME_MAX} characters", EXIT_USAGE)

    async def run() -> str:
        engine = make_engine(url)
        try:
            async with make_session_factory(engine)() as session:
                owner = await users_repo.get_or_create_admin(session)
                _, plaintext = await api_keys_repo.create(
                    session, owner_user_id=owner.id, name=name, scope=scope
                )
                await session.commit()
                return plaintext
        finally:
            await engine.dispose()

    try:
        plaintext = asyncio.run(run())
    except (OSError, SQLAlchemyError) as exc:
        return _fail(f"database error ({type(exc).__name__}); no token was created", 1)
    sys.stdout.write(f"{plaintext}\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments; return the process exit code."""
    args = build_parser().parse_args(argv)
    if args.command == "secrets" and args.secrets_command == "rotate":
        return _rotate()
    if args.command == "admin" and args.admin_command == "create-key":
        return _create_key(args.scope, args.name)
    return 0
