"""D1 — aggregators must read events.jsonl + supervisor.jsonl together.

Before this fix `consciousness_metrics.py` and `evolution_stats.py` only
parsed `events.jsonl`. Events that landed in `supervisor.jsonl` (worker_boot,
launcher_start, deps_sync_ok, reset_unsynced_*, plan_generated routed via
supervisor, etc.) were silently dropped — ~40% of total events.

These tests pin the merged-load behavior so future regressions surface.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from scripts.consciousness_metrics import ConsciousnessMetrics


def _write_jsonl(path: pathlib.Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def test_consciousness_metrics_loads_both_event_logs(tmp_path):
    logs = tmp_path / "logs"
    _write_jsonl(logs / "events.jsonl", [
        {"ts": "2026-04-26T10:00:00+00:00", "type": "task_received"},
        {"ts": "2026-04-26T10:01:00+00:00", "type": "llm_round"},
        {"ts": "2026-04-25T23:59:00+00:00", "type": "task_done"},
    ])
    _write_jsonl(logs / "supervisor.jsonl", [
        {"ts": "2026-04-26T09:55:00+00:00", "type": "launcher_start"},
        {"ts": "2026-04-26T09:56:00+00:00", "type": "worker_boot"},
        {"ts": "2026-04-25T22:00:00+00:00", "type": "deps_sync_ok"},
    ])

    metrics = ConsciousnessMetrics(data_dir=tmp_path)
    events = metrics._load_events_for_date("2026-04-26")

    types = [e["type"] for e in events]
    assert "task_received" in types
    assert "llm_round" in types
    assert "launcher_start" in types
    assert "worker_boot" in types
    assert "task_done" not in types  # different date
    assert "deps_sync_ok" not in types  # different date

    # Merged result is sorted by ts
    timestamps = [e["ts"] for e in events]
    assert timestamps == sorted(timestamps)


def test_consciousness_metrics_handles_missing_supervisor_log(tmp_path):
    logs = tmp_path / "logs"
    _write_jsonl(logs / "events.jsonl", [
        {"ts": "2026-04-26T10:00:00+00:00", "type": "task_received"},
    ])
    # supervisor.jsonl intentionally absent

    metrics = ConsciousnessMetrics(data_dir=tmp_path)
    events = metrics._load_events_for_date("2026-04-26")
    assert len(events) == 1
    assert events[0]["type"] == "task_received"


def test_consciousness_metrics_handles_missing_events_log(tmp_path):
    logs = tmp_path / "logs"
    _write_jsonl(logs / "supervisor.jsonl", [
        {"ts": "2026-04-26T09:55:00+00:00", "type": "launcher_start"},
    ])
    # events.jsonl intentionally absent

    metrics = ConsciousnessMetrics(data_dir=tmp_path)
    events = metrics._load_events_for_date("2026-04-26")
    assert len(events) == 1
    assert events[0]["type"] == "launcher_start"


def test_evolution_stats_reads_both_logs(tmp_path, monkeypatch):
    """read_events_log() merges plan_generated from both files."""
    logs = tmp_path / "logs"
    _write_jsonl(logs / "events.jsonl", [
        {"ts": "2026-04-26T10:00:00+00:00", "type": "plan_generated"},
        {"ts": "2026-04-26T10:01:00+00:00", "type": "shareholder_gate"},
    ])
    _write_jsonl(logs / "supervisor.jsonl", [
        {"ts": "2026-04-26T09:55:00+00:00", "type": "plan_generated"},
        {"ts": "2026-04-26T09:56:00+00:00", "type": "gate_triggered"},
        {"ts": "2026-04-26T09:57:00+00:00", "type": "worker_boot"},
    ])

    import scripts.evolution_stats as ev_stats
    monkeypatch.setattr(ev_stats, "DATA_DIR", tmp_path)

    stats = ev_stats.read_events_log()
    assert stats["plans_generated"] == 2  # both files counted
    assert stats["gates_triggered"] == 2  # shareholder_gate + gate_triggered
    assert stats["total_events"] == 5     # all rows across both files
