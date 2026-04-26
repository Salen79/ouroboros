"""Verify scenario YAML loader rejects malformed files and accepts A."""
from __future__ import annotations

import pathlib
import textwrap

import pytest

from eval.scenario import load_scenario, ScenarioLoadError, SCENARIOS_DIR


def test_load_scenario_a():
    s = load_scenario("A_infra_confusion")
    assert s.id == "A_infra_confusion"
    assert s.mode == "direct"
    assert s.version >= 1
    assert "D16" in s.covers
    assert s.judge is not None
    assert "anthropic/claude-sonnet-4.6" in s.judge.models
    assert "openai/gpt-4.1" in s.judge.models
    assert s.has_verdict_source()


def test_missing_required_field_rejected(tmp_path, monkeypatch):
    bad = tmp_path / "X_bad.yaml"
    bad.write_text(textwrap.dedent("""
        id: X_bad
        title: "no version"
        covers: [D1]
        mode: direct
        input: {text: "hi"}
        programmatic_checks:
          - kind: tool_called
            tool_name: anything
    """).strip(), encoding="utf-8")
    monkeypatch.setattr("eval.scenario.SCENARIOS_DIR", tmp_path)
    with pytest.raises(ScenarioLoadError, match="missing fields"):
        load_scenario("X_bad")


def test_no_verdict_source_rejected(tmp_path, monkeypatch):
    bad = tmp_path / "Y_empty.yaml"
    bad.write_text(textwrap.dedent("""
        id: Y_empty
        title: "no checks no judge"
        version: 1
        covers: []
        mode: direct
        input: {text: "x"}
    """).strip(), encoding="utf-8")
    monkeypatch.setattr("eval.scenario.SCENARIOS_DIR", tmp_path)
    with pytest.raises(ScenarioLoadError, match="neither programmatic_checks"):
        load_scenario("Y_empty")
