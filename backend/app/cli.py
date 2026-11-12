"""Command line interface. Subcommands are added by later tasks."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from app.build_info import VERSION


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bambubridge")
    parser.add_argument("--version", action="version", version=f"bambubridge {VERSION}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments; return the process exit code."""
    build_parser().parse_args(argv)
    return 0
