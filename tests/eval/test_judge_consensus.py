"""Judge consensus aggregation table — pure logic, no LLM calls."""
from __future__ import annotations

from eval.judge import _consensus, _normalize_verdict


def test_all_pass():
    assert _consensus(["pass", "pass"]) == ("pass", "all_judges_pass")


def test_all_fail():
    v, r = _consensus(["fail", "fail"])
    assert v == "fail"


def test_mixed_pass_fail_inconclusive():
    v, r = _consensus(["pass", "fail"])
    assert v == "inconclusive" and r == "judge_disagreement"


def test_pass_and_inconclusive():
    v, r = _consensus(["pass", "inconclusive"])
    assert v == "inconclusive" and r == "judge_low_confidence"


def test_fail_dominates_inconclusive():
    v, r = _consensus(["fail", "inconclusive"])
    assert v == "fail"


def test_normalize_verdict():
    assert _normalize_verdict("PASS") == "pass"
    assert _normalize_verdict("garbage") == "inconclusive"
    assert _normalize_verdict(None) == "inconclusive"
