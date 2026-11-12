from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]


def test_pytest_aborts_without_test_database_url():
    env = {k: v for k, v in os.environ.items() if k != "BAMBUBRIDGE_TEST_DATABASE_URL"}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit/test_problem.py", "-p", "no:cacheprovider"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 4
    assert "BAMBUBRIDGE_TEST_DATABASE_URL is not set" in result.stdout + result.stderr
    assert "passed" not in result.stdout
