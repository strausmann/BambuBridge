"""The installed package must be self-contained: the entrypoint migrates before serving."""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]


def test_wheel_ships_migration_environment_and_baseline(tmp_path: Path):
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not installed")
    subprocess.run(  # noqa: S603 - fixed argv, no shell
        [uv, "build", "--wheel", "--out-dir", str(tmp_path), str(BACKEND_DIR)],
        check=True,
        capture_output=True,
        timeout=300,
    )
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1
    names = set(zipfile.ZipFile(wheels[0]).namelist())

    for required in (
        "app/migrations/__init__.py",
        "app/migrations/env.py",
        "app/migrations/script.py.mako",
        "app/migrations/versions/2026_11_12_0001_baseline.py",
    ):
        assert required in names, f"{required} missing from wheel"
