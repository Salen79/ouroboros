"""Programmatic check primitives.

Each check function takes (check_spec_dict, trace_dict) and returns
a dict {kind, args, passed, detail}. Trace shape comes from
execute.py:_snapshot_logs + the subprocess result.
"""
from __future__ import annotations

import hashlib
import json
import logging
import pathlib
import re
from typing import Any, Callable, Dict, List

log = logging.getLogger(__name__)


def _events_streams(trace: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Merge events.jsonl + supervisor.jsonl + tools.jsonl into one stream.

    Per D1: production splits across two event buses; eval must read both.
    """
    captured = trace.get("captured_logs") or {}
    merged: List[Dict[str, Any]] = []
    for key in ("events.jsonl", "supervisor.jsonl", "tools.jsonl"):
        items = captured.get(key) or []
        if isinstance(items, list):
            merged.extend(items)
    # Also include events bubbled up via the subprocess result.
    sub_result = trace.get("result") or {}
    merged.extend(sub_result.get("events") or [])
    return merged


def _drive_root(trace: Dict[str, Any]) -> pathlib.Path:
    return pathlib.Path(trace["_drive_root"])


def _matches_where(event: Dict[str, Any], where: Dict[str, Any]) -> bool:
    """Loose substring/equality match on event fields. Special key `args_contains`
    matches if substring appears anywhere in str(args)."""
    for k, v in where.items():
        if k == "args_contains":
            if v not in json.dumps(event.get("args", event.get("payload", {})), default=str):
                return False
        elif k == "result_contains":
            if v not in json.dumps(event.get("result", ""), default=str):
                return False
        elif k == "text_contains":
            if v not in str(event.get("text", "")):
                return False
        elif k == "prompt_contains":
            if v not in json.dumps(event.get("args", {}), default=str):
                return False
        else:
            if str(event.get(k, "")) != str(v):
                return False
    return True


def _check_event_present(spec: Dict[str, Any], trace: Dict[str, Any]) -> Dict[str, Any]:
    event_type = spec.get("event_type")
    where = spec.get("where") or {}
    matches = [
        e for e in _events_streams(trace)
        if e.get("type") == event_type and _matches_where(e, where)
    ]
    return {
        "kind": "event_present",
        "args": {"event_type": event_type, "where": where},
        "passed": len(matches) > 0,
        "detail": f"{len(matches)} matching event(s)",
    }


def _check_event_absent(spec: Dict[str, Any], trace: Dict[str, Any]) -> Dict[str, Any]:
    event_type = spec.get("event_type")
    where = spec.get("where") or {}
    matches = [
        e for e in _events_streams(trace)
        if e.get("type") == event_type and _matches_where(e, where)
    ]
    return {
        "kind": "event_absent",
        "args": {"event_type": event_type, "where": where},
        "passed": len(matches) == 0,
        "detail": f"{len(matches)} unwanted event(s)",
    }


def _check_tool_called(spec: Dict[str, Any], trace: Dict[str, Any]) -> Dict[str, Any]:
    tool_name = spec.get("tool_name")
    captured = (trace.get("captured_logs") or {}).get("tools.jsonl") or []
    matches = [t for t in captured if t.get("tool") == tool_name or t.get("name") == tool_name]
    return {
        "kind": "tool_called",
        "args": {"tool_name": tool_name},
        "passed": len(matches) > 0,
        "detail": f"{len(matches)} call(s) to {tool_name}",
    }


def _check_tool_not_called(spec: Dict[str, Any], trace: Dict[str, Any]) -> Dict[str, Any]:
    tool_name = spec.get("tool_name")
    args_contains = spec.get("args_contains")
    captured = (trace.get("captured_logs") or {}).get("tools.jsonl") or []
    matches = []
    for t in captured:
        if t.get("tool") != tool_name and t.get("name") != tool_name:
            continue
        if args_contains:
            arg_blob = json.dumps(t.get("args", {}), default=str)
            if args_contains not in arg_blob:
                continue
        matches.append(t)
    return {
        "kind": "tool_not_called",
        "args": {"tool_name": tool_name, "args_contains": args_contains},
        "passed": len(matches) == 0,
        "detail": f"{len(matches)} forbidden call(s)",
    }


def _check_file_unchanged(spec: Dict[str, Any], trace: Dict[str, Any]) -> Dict[str, Any]:
    rel = spec.get("path")
    expected_sha = spec.get("expected_sha256")  # optional; if absent we just check existence
    drive = _drive_root(trace)
    target = drive / rel
    if not target.exists():
        return {"kind": "file_unchanged", "args": {"path": rel}, "passed": False,
                "detail": "file not present"}
    if expected_sha:
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        return {"kind": "file_unchanged", "args": {"path": rel, "expected_sha256": expected_sha},
                "passed": actual == expected_sha,
                "detail": f"sha256={actual[:12]} (expected {expected_sha[:12]})"}
    return {"kind": "file_unchanged", "args": {"path": rel}, "passed": True,
            "detail": "exists; no sha given to compare"}


def _check_file_contains(spec: Dict[str, Any], trace: Dict[str, Any]) -> Dict[str, Any]:
    rel = spec.get("path")
    needle = spec.get("substring") or spec.get("regex")
    is_regex = "regex" in spec
    drive = _drive_root(trace)
    target = drive / rel
    if not target.exists():
        return {"kind": "file_contains", "args": {"path": rel}, "passed": False,
                "detail": "file not present"}
    content = target.read_text(encoding="utf-8", errors="replace")
    if is_regex:
        ok = re.search(needle, content) is not None
    else:
        ok = needle in content
    return {"kind": "file_contains", "args": {"path": rel, "needle": needle},
            "passed": ok, "detail": ("match" if ok else "no match")}


def _check_budget_under(spec: Dict[str, Any], trace: Dict[str, Any]) -> Dict[str, Any]:
    cap = float(spec.get("usd"))
    spent = float(trace.get("_scenario_spend_usd") or 0.0)
    return {"kind": "budget_under", "args": {"usd": cap},
            "passed": spent < cap, "detail": f"spent ${spent:.4f}"}


def _check_rounds_under(spec: Dict[str, Any], trace: Dict[str, Any]) -> Dict[str, Any]:
    cap = int(spec.get("rounds"))
    rounds = sum(
        1 for e in _events_streams(trace) if e.get("type") == "llm_round"
    )
    return {"kind": "rounds_under", "args": {"rounds": cap},
            "passed": rounds < cap, "detail": f"observed {rounds} llm_round events"}


CHECK_REGISTRY: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = {
    "event_present": _check_event_present,
    "event_absent": _check_event_absent,
    "tool_called": _check_tool_called,
    "tool_not_called": _check_tool_not_called,
    "file_unchanged": _check_file_unchanged,
    "file_contains": _check_file_contains,
    "budget_under": _check_budget_under,
    "rounds_under": _check_rounds_under,
}


def run_checks(checks: List[Dict[str, Any]], trace: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for spec in checks:
        kind = spec.get("kind")
        fn = CHECK_REGISTRY.get(kind)
        if fn is None:
            out.append({"kind": kind, "args": spec, "passed": False,
                        "detail": f"unknown check kind {kind!r}"})
            continue
        try:
            out.append(fn(spec, trace))
        except Exception as e:
            out.append({"kind": kind, "args": spec, "passed": False,
                        "detail": f"check raised {type(e).__name__}: {e}"})
    return out
