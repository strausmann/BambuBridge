from __future__ import annotations

import pytest

from app.build_info import VERSION
from app.cli import main


def test_version_flag_prints_version_and_exits_zero(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0
    assert VERSION in capsys.readouterr().out


def test_no_arguments_returns_zero():
    assert main([]) == 0
