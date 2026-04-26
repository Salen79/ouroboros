"""Programmatic check primitives — unit-level."""
from __future__ import annotations

import pathlib

from eval.checks import run_checks


def _trace(events=None, supervisor_events=None, tools=None,
           drive_root=".", spend=0.0):
    return {
        "captured_logs": {
            "events.jsonl": events or [],
            "supervisor.jsonl": supervisor_events or [],
            "tools.jsonl": tools or [],
            "task_results": [],
        },
        "result": {"events": [], "final_text": "", "usage": {}},
        "_drive_root": drive_root,
        "_scenario_spend_usd": spend,
    }


def test_event_present_pass():
    trace = _trace(events=[{"type": "task_received"}])
    out = run_checks([{"kind": "event_present", "event_type": "task_received"}], trace)
    assert out[0]["passed"]


def test_event_present_fail():
    trace = _trace(events=[{"type": "task_done"}])
    out = run_checks([{"kind": "event_present", "event_type": "stuck_model_escalation"}], trace)
    assert not out[0]["passed"]


def test_tool_called_and_not_called():
    trace = _trace(tools=[{"tool": "chromadb_stats", "args": {}}])
    out = run_checks([
        {"kind": "tool_called", "tool_name": "chromadb_stats"},
        {"kind": "tool_not_called", "tool_name": "run_shell",
         "args_contains": "PersistentClient"},
    ], trace)
    assert out[0]["passed"] and out[1]["passed"]


def test_tool_not_called_catches_forbidden_substring():
    trace = _trace(tools=[
        {"tool": "run_shell", "args": {"cmd": "python -c 'import chromadb; chromadb.PersistentClient(path=\"/tmp/x\")'"}},
    ])
    out = run_checks([
        {"kind": "tool_not_called", "tool_name": "run_shell",
         "args_contains": "PersistentClient"},
    ], trace)
    assert not out[0]["passed"]


def test_rounds_under():
    events = [{"type": "llm_round"}] * 3
    out = run_checks([{"kind": "rounds_under", "rounds": 5}], _trace(events=events))
    assert out[0]["passed"]
    out2 = run_checks([{"kind": "rounds_under", "rounds": 2}], _trace(events=events))
    assert not out2[0]["passed"]


def test_unknown_kind_marked_failed():
    out = run_checks([{"kind": "telepathy_check", "must": True}], _trace())
    assert not out[0]["passed"]
    assert "unknown check kind" in out[0]["detail"]


def test_file_unchanged_existence(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "identity.md").write_text("hello")
    trace = _trace(drive_root=str(tmp_path))
    out = run_checks([{"kind": "file_unchanged", "path": "memory/identity.md"}], trace)
    assert out[0]["passed"]
