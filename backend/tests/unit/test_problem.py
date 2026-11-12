from __future__ import annotations

from app.schemas.problem import ProblemDetail


def test_problem_detail_defaults():
    p = ProblemDetail(title="Not found", status=404)
    assert p.type == "about:blank"
    assert p.detail is None
    assert p.extensions == {}
