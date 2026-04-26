"""D17 — worker destructive-keyword guard emits visible refusal events.

Before this fix, a refused task only produced a Telegram message routed
through the worker's out_q (chat-history pollution) and an entry in
supervisor.jsonl. The dashboard / consciousness aggregators (which read
events.jsonl + supervisor.jsonl together) had no `task_refused_by_guard`
type to count, and the Shareholder couldn't see the refusal except by
inspecting raw logs.

These tests pin three things:
  1. `_match_destructive_keyword` returns the matched substring (or None).
  2. `_emit_guard_refusal` writes the right shapes to all three sinks
     (out_q, supervisor.jsonl, events.jsonl) with the matched keyword and
     task preview present.
  3. `build_architecture_snapshot._populate_safety_prevent_counts` aggregates
     refusals from both events.jsonl and supervisor.jsonl into the
     Destructive-keyword guard item's `count` field for the dashboard.
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, List

import pytest


# ---------------------------------------------------------------------------
# 1. _match_destructive_keyword
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("удали логи за апрель",            "удал"),
    ("Please refactor the auth flow",   "refactor"),
    ("delete file old.py",              "delete file"),
    ("Перепиши README.md",              "перепиши"),
    ("CLEAN UP outdated comments",      "clean up"),
    ("normal task: deploy prism v2",    None),
    ("",                                None),
])
def test_match_destructive_keyword(text, expected):
    from supervisor.workers import _match_destructive_keyword
    assert _match_destructive_keyword(text) == expected


# ---------------------------------------------------------------------------
# 2. _emit_guard_refusal — three sinks
# ---------------------------------------------------------------------------

class _FakeQueue:
    """Stand-in for multiprocessing.Queue — captures puts in a list."""
    def __init__(self) -> None:
        self.items: List[Dict[str, Any]] = []

    def put(self, evt: Dict[str, Any]) -> None:
        self.items.append(evt)


def _read_jsonl(path: pathlib.Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def test_emit_guard_refusal_writes_all_three_sinks(tmp_path):
    from supervisor.workers import _emit_guard_refusal

    out_q = _FakeQueue()
    task = {
        "id": "task-abc-123",
        "chat_id": 999,
        "text": "удали все .pyc файлы из репозитория и перепиши .gitignore",
    }

    _emit_guard_refusal(
        wid=2, task=task, matched_keyword="удал",
        out_q=out_q, drive_root=tmp_path,
    )

    # --- (a) Telegram out_q event: system progress msg, not chat ---
    assert len(out_q.items) == 1
    msg = out_q.items[0]
    assert msg["type"] == "send_message"
    assert msg["chat_id"] == 999
    assert msg["worker_id"] == 2
    assert msg["is_worker"] is True
    # is_progress=True keeps refusal out of chat.jsonl (system event,
    # not conversation — D17 contract).
    assert msg["is_progress"] is True
    assert "guard" in msg["text"].lower()
    assert "удал" in msg["text"]

    # --- (b) supervisor.jsonl: existing audit entry, now with matched_keyword ---
    sup_rows = _read_jsonl(tmp_path / "logs" / "supervisor.jsonl")
    assert len(sup_rows) == 1
    sup = sup_rows[0]
    assert sup["type"] == "worker_destructive_blocked"
    assert sup["task_id"] == "task-abc-123"
    assert sup["matched_keyword"] == "удал"
    assert "удали все .pyc" in sup["text_snippet"]

    # --- (c) events.jsonl: NEW visible event for dashboard / aggregators ---
    ev_rows = _read_jsonl(tmp_path / "logs" / "events.jsonl")
    assert len(ev_rows) == 1
    ev = ev_rows[0]
    assert ev["type"] == "task_refused_by_guard"
    assert ev["task_id"] == "task-abc-123"
    assert ev["guard"] == "destructive_keyword"
    assert ev["matched_keyword"] == "удал"
    assert "удали все .pyc" in ev["task_text_preview"]
    # Preview must be capped at 200 chars to bound log size.
    assert len(ev["task_text_preview"]) <= 200


def test_emit_guard_refusal_truncates_long_preview(tmp_path):
    """Task text > 200 chars must be capped in both the log payload and
    the Telegram message (which trims at 120 + ellipsis)."""
    from supervisor.workers import _emit_guard_refusal

    out_q = _FakeQueue()
    long_text = "удали " + ("very long context " * 30)  # ~520 chars
    _emit_guard_refusal(
        wid=0, task={"id": "x", "chat_id": 1, "text": long_text},
        matched_keyword="удал", out_q=out_q, drive_root=tmp_path,
    )

    ev = _read_jsonl(tmp_path / "logs" / "events.jsonl")[0]
    assert len(ev["task_text_preview"]) == 200

    sent_text = out_q.items[0]["text"]
    assert "…" in sent_text  # ellipsis after truncation


# ---------------------------------------------------------------------------
# 3. build_architecture_snapshot — dashboard counter aggregation
# ---------------------------------------------------------------------------

def _write_jsonl(path: pathlib.Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def test_safety_prevent_counts_aggregates_both_logs(tmp_path, monkeypatch):
    """The Destructive-keyword guard item gets a `count` summed from
    events.jsonl (`task_refused_by_guard`) AND supervisor.jsonl
    (`worker_destructive_blocked`) — D1 dual-log compatibility."""
    from scripts import build_architecture_snapshot as bas

    _write_jsonl(tmp_path / "logs" / "events.jsonl", [
        {"ts": "2026-04-26T10:00:00+00:00", "type": "task_refused_by_guard",
         "task_id": "t1", "matched_keyword": "удал"},
        {"ts": "2026-04-26T10:01:00+00:00", "type": "task_refused_by_guard",
         "task_id": "t2", "matched_keyword": "refactor"},
        {"ts": "2026-04-26T10:02:00+00:00", "type": "task_done"},  # noise
    ])
    _write_jsonl(tmp_path / "logs" / "supervisor.jsonl", [
        {"ts": "2026-04-25T09:00:00+00:00", "type": "worker_destructive_blocked",
         "task_id": "t0", "matched_keyword": "delete file"},
        {"ts": "2026-04-25T09:01:00+00:00", "type": "worker_boot"},  # noise
    ])

    monkeypatch.setattr(bas, "DATA_ROOT", tmp_path)

    # Reset state so test is hermetic regardless of import order.
    prevent = next(b for b in bas.SAFETY_BLOCKS if b["id"] == "safety_prevent")
    for it in prevent["items"]:
        it.pop("count", None)
        it.pop("count_source", None)

    bas._populate_safety_prevent_counts()

    item = next(it for it in prevent["items"]
                if str(it.get("ref", "")).startswith("supervisor/workers.py:320-351"))
    # 2 from events.jsonl + 1 from supervisor.jsonl = 3
    assert item["count"] == 3
    assert "task_refused_by_guard" in item["count_source"]


def test_safety_prevent_counts_handles_missing_logs(tmp_path, monkeypatch):
    """Missing event logs → count = 0, no exception."""
    from scripts import build_architecture_snapshot as bas

    monkeypatch.setattr(bas, "DATA_ROOT", tmp_path)
    prevent = next(b for b in bas.SAFETY_BLOCKS if b["id"] == "safety_prevent")
    for it in prevent["items"]:
        it.pop("count", None)
        it.pop("count_source", None)

    bas._populate_safety_prevent_counts()

    item = next(it for it in prevent["items"]
                if str(it.get("ref", "")).startswith("supervisor/workers.py:320-351"))
    assert item["count"] == 0


# ---------------------------------------------------------------------------
# 4. Integration: worker_main path — destructive task is refused before agent
# ---------------------------------------------------------------------------

def test_worker_main_refuses_destructive_task_before_agent(tmp_path, monkeypatch):
    """End-to-end via worker_main: feeding a destructive task + shutdown
    sentinel must trigger _emit_guard_refusal exactly once and NEVER call
    agent.handle_task."""
    from supervisor import workers

    handle_task_calls: List[Any] = []

    class _FakeAgent:
        def handle_task(self, task):
            handle_task_calls.append(task)
            return []

    monkeypatch.setattr(
        "ouroboros.agent.make_agent",
        lambda **kw: _FakeAgent(),
    )

    class _InQueue:
        def __init__(self, items):
            self._items = list(items)
        def get(self):
            return self._items.pop(0) if self._items else {"type": "shutdown"}

    in_q = _InQueue([
        {"id": "t1", "chat_id": 5, "text": "почисти кеш и удали временные файлы"},
        {"type": "shutdown"},
    ])
    out_q = _FakeQueue()

    workers.worker_main(wid=7, in_q=in_q, out_q=out_q,
                        repo_dir=str(pathlib.Path(__file__).resolve().parents[1]),
                        drive_root=str(tmp_path))

    assert handle_task_calls == []  # refused before agent

    # Refusal Telegram event present
    refusals = [m for m in out_q.items if m.get("type") == "send_message"]
    assert len(refusals) == 1
    assert refusals[0]["is_progress"] is True

    # events.jsonl populated
    ev_rows = _read_jsonl(tmp_path / "logs" / "events.jsonl")
    refused = [e for e in ev_rows if e["type"] == "task_refused_by_guard"]
    assert len(refused) == 1
    assert refused[0]["task_id"] == "t1"
    assert refused[0]["matched_keyword"] in ("почист", "удал")


def test_worker_main_passes_safe_task_to_agent(tmp_path, monkeypatch):
    """Sanity: a non-destructive task still reaches agent.handle_task and
    does NOT generate a refusal event."""
    from supervisor import workers

    handle_task_calls: List[Any] = []

    class _FakeAgent:
        def handle_task(self, task):
            handle_task_calls.append(task)
            return [{"type": "task_done", "task_id": task.get("id")}]

    monkeypatch.setattr(
        "ouroboros.agent.make_agent",
        lambda **kw: _FakeAgent(),
    )

    class _InQueue:
        def __init__(self, items):
            self._items = list(items)
        def get(self):
            return self._items.pop(0) if self._items else {"type": "shutdown"}

    in_q = _InQueue([
        {"id": "safe-1", "chat_id": 5, "text": "build a status report"},
        {"type": "shutdown"},
    ])
    out_q = _FakeQueue()

    workers.worker_main(wid=3, in_q=in_q, out_q=out_q,
                        repo_dir=str(pathlib.Path(__file__).resolve().parents[1]),
                        drive_root=str(tmp_path))

    assert len(handle_task_calls) == 1
    ev_rows = _read_jsonl(tmp_path / "logs" / "events.jsonl")
    assert [e for e in ev_rows if e["type"] == "task_refused_by_guard"] == []


def test_worker_main_allow_destructive_override_bypasses_guard(tmp_path, monkeypatch):
    """`_allow_destructive=True` (set when Shareholder explicitly green-lights
    a destructive task) bypasses the keyword guard."""
    from supervisor import workers

    handle_task_calls: List[Any] = []

    class _FakeAgent:
        def handle_task(self, task):
            handle_task_calls.append(task)
            return []

    monkeypatch.setattr(
        "ouroboros.agent.make_agent",
        lambda **kw: _FakeAgent(),
    )

    class _InQueue:
        def __init__(self, items):
            self._items = list(items)
        def get(self):
            return self._items.pop(0) if self._items else {"type": "shutdown"}

    in_q = _InQueue([
        {"id": "ok", "chat_id": 1, "text": "удали logs", "_allow_destructive": True},
        {"type": "shutdown"},
    ])
    out_q = _FakeQueue()

    workers.worker_main(wid=1, in_q=in_q, out_q=out_q,
                        repo_dir=str(pathlib.Path(__file__).resolve().parents[1]),
                        drive_root=str(tmp_path))

    assert len(handle_task_calls) == 1
    assert _read_jsonl(tmp_path / "logs" / "events.jsonl") == []
