"""Regression tests for Phase B framework fixes (B-O2 / B-O6 / B-O7)."""
from __future__ import annotations

import json
import pathlib

from eval.checks import _events_streams
from eval.execute import _resolve_agent_python


# --- B-O7 dedup ---

def test_events_streams_dedupes_overlap():
    """Same (type, ts, task_id, round) appearing in events.jsonl AND
    subprocess result events list MUST count once."""
    e = {"type": "task_done", "ts": "2026-04-26T08:00:00Z", "task_id": "abc", "round": None}
    trace = {
        "captured_logs": {
            "events.jsonl": [e],
            "supervisor.jsonl": [],
            "tools.jsonl": [],
        },
        "result": {"events": [e]},
    }
    merged = _events_streams(trace)
    assert len(merged) == 1, f"expected 1 event after dedup, got {len(merged)}"


def test_events_streams_keeps_distinct_events_by_round():
    """Two llm_round events with different round numbers must both appear."""
    e1 = {"type": "llm_round", "task_id": "abc", "round": 1}
    e2 = {"type": "llm_round", "task_id": "abc", "round": 2}
    trace = {
        "captured_logs": {"events.jsonl": [e1, e2], "supervisor.jsonl": [], "tools.jsonl": []},
        "result": {"events": []},
    }
    merged = _events_streams(trace)
    assert len(merged) == 2


def test_events_streams_dedupes_when_subprocess_event_lacks_ts():
    """Real-world case: events.jsonl has ts; subprocess events list (from
    agent.handle_task return) lacks ts. Same (type, task_id, round) must
    still dedupe."""
    on_disk = {"type": "task_done", "ts": "2026-04-26T08:32:03Z",
               "task_id": "abc", "round": None}
    in_memory = {"type": "task_done", "task_id": "abc", "round": None}
    trace = {
        "captured_logs": {"events.jsonl": [on_disk], "supervisor.jsonl": [], "tools.jsonl": []},
        "result": {"events": [in_memory]},
    }
    merged = _events_streams(trace)
    assert len(merged) == 1, f"got {merged}"


def test_events_streams_subprocess_only_event_kept():
    """Event present only in subprocess result (not on disk) must still appear."""
    e_disk = {"type": "task_received", "ts": "1", "task_id": "abc"}
    e_only_sub = {"type": "queue_drain", "ts": "2", "task_id": "abc"}
    trace = {
        "captured_logs": {"events.jsonl": [e_disk], "supervisor.jsonl": [], "tools.jsonl": []},
        "result": {"events": [e_only_sub]},
    }
    merged = _events_streams(trace)
    types = [e["type"] for e in merged]
    assert "task_received" in types and "queue_drain" in types


# --- B-O6 final_text from task_results ---

def test_final_text_reader_pulls_from_task_results(tmp_path):
    from eval._subprocess_runner import _read_final_text_from_task_result
    (tmp_path / "task_results").mkdir()
    (tmp_path / "task_results" / "task42.json").write_text(json.dumps({
        "task_id": "task42",
        "status": "completed",
        "result": "the actual response text the judge needs",
    }))
    out = _read_final_text_from_task_result(tmp_path, "task42")
    assert out == "the actual response text the judge needs"


def test_final_text_reader_returns_empty_when_missing(tmp_path):
    from eval._subprocess_runner import _read_final_text_from_task_result
    out = _read_final_text_from_task_result(tmp_path, "missing_id")
    assert out == ""


def test_final_text_reader_handles_no_task_id(tmp_path):
    from eval._subprocess_runner import _read_final_text_from_task_result
    assert _read_final_text_from_task_result(tmp_path, "") == ""


# --- B-O2 venv resolution ---

def test_resolve_agent_python_uses_ouroboros_venv():
    """The agent subprocess must use ~/.ouroboros-venv/bin/python when
    that venv exists — that's where chromadb and other agent deps live."""
    venv = pathlib.Path.home() / ".ouroboros-venv" / "bin" / "python"
    if venv.exists():
        assert _resolve_agent_python() == str(venv)


def test_resolve_agent_python_honors_override(monkeypatch, tmp_path):
    fake = tmp_path / "fake_python"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("EVAL_AGENT_PYTHON", str(fake))
    assert _resolve_agent_python() == str(fake)


# --- isolation snapshot ---

def test_temp_drive_root_snapshot_writes_logs_and_state(tmp_path):
    from eval.isolation import temp_drive_root
    snapshot = tmp_path / "snap"
    with temp_drive_root("X_test", "run123", snapshot_dir=snapshot) as drive:
        (drive / "logs" / "events.jsonl").write_text('{"type":"hi"}\n')
        (drive / "task_results" / "abc.json").write_text('{"result":"ok"}')
        (drive / "memory" / "scratchpad.md").write_text("scratch")
    assert (snapshot / "logs" / "events.jsonl").read_text() == '{"type":"hi"}\n'
    assert (snapshot / "task_results" / "abc.json").exists()
    assert (snapshot / "memory" / "scratchpad.md").read_text() == "scratch"


def test_temp_drive_root_no_snapshot_when_none(tmp_path):
    from eval.isolation import temp_drive_root
    with temp_drive_root("Y_test", "run456") as drive:
        (drive / "logs" / "events.jsonl").write_text("{}")
    # base parent should be cleaned; nothing to assert beyond no-crash.
