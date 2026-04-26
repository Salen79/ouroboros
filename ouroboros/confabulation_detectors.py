"""Confabulation detectors — heuristic post-hoc scanners over THAI logs.

Three independent scans, each emitting alerts into a shared JSON store:

  D-1  Empty/all-OK tool result followed by a confident bad-news report.
  D-2  Panic vocabulary ("критическая проблема", "🔴", "down", ...) in
       outgoing chat messages.
  D-3  Phantom facts — concrete numbers / IPs / ports / timestamps in an
       outgoing report that do not appear in any tool result for that
       task, and were not in the originating user prompt.

Detectors are *advisory only*. They never block THAI; they only annotate
the BEZOPASNOST organ on the architecture dashboard so that the operator
can spot a recurring pattern over days, not just one task.

Inputs:
  - ouroboros-data/logs/events.jsonl  (per-round timing + task lifecycle)
  - ouroboros-data/logs/tools.jsonl   (tool args + result_preview, the
                                       only place we actually see tool I/O)
  - ouroboros-data/logs/chat.jsonl    (outgoing messages — D-2 only)
  - ouroboros-data/task_results/*.json (per-task final response — D-1, D-3)

Output:
  - state/confabulation_alerts.json   (counters + last 50 alerts)
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import hashlib
import json
import pathlib
import re
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Vocabulary / patterns
# ---------------------------------------------------------------------------

PANIC_TERMS_RU = (
    "критическая проблема",
    "критический",
    "критич",
    "🔴",
    "срочно",
    "не работает",
    "упал",
    "упала",
    "лежит",
    "сломал",
    "сломан",
    "авари",
    "поломк",
    "крах",
    "паник",
)
PANIC_TERMS_EN = (
    "critical",
    "emergency",
    "down",
    "failure",
    "crashed",
    "outage",
    "panic",
    "urgent",
    "alert!",
)

EMPTY_RESULT_MARKERS = (
    "no results",
    "no skills matching",
    "no matching",
    "ничего не найдено",
    "пусто",
    "(empty)",
    "[]",
    "{}",
    "no entries",
    "0 items",
)

ERROR_MARKERS = (
    "error:",
    "❌",
    "failed",
    "stderr:",
    "exception",
    "traceback",
    "connection refused",
    "connection timed out",
)

# Tools that surface operational state. If the most recent ops-class tool
# in a task returned only "active"/"OK"/empty, but the report is ringing
# alarm bells, that is the D-1 pattern.
OPS_TOOLS = {
    "run_ops_check",
    "read_service_logs",
    "read_logs",
    "check_url",
    "ops_check",
}

# Patterns that count as "concrete fact" candidates in D-3.
# We deliberately keep the list narrow — we want phantom *specifics*, not
# every digit. Each pattern emits a normalised token used for substring
# matching against the tool-result corpus.
_FACT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # IPv4
    ("ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    # HTTP status with magnitude (502, 503, 504, 500, 401, 403, 404, 429, 5xx)
    ("status_code", re.compile(r"\b(?:1\d{2}|2\d{2}|3\d{2}|4\d{2}|5\d{2})\b")),
    # TCP/UDP-style ports >=1000 (avoid matching years, plain counts)
    ("port", re.compile(r"\b(?:127\.0\.0\.1:|порт[уеа]?\s*|port\s*|:)([1-9]\d{3,4})\b", re.IGNORECASE)),
    # Hour:minute timestamp (12:24, 23:55, 06:13, etc.)
    ("time", re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:UTC|МСК|MSK)?\b")),
    # Calendar date short forms (Apr 03, 12 апреля, 2026-04-26)
    ("date", re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2})\b")),
]

# Patterns we strip from the matchable surface before D-3 fact extraction.
# Markdown decorations are noise, not facts.
_MD_NOISE = re.compile(r"[`*_>]+")


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Alert:
    id: str
    ts: str
    type: str               # "D-1" | "D-2" | "D-3"
    severity: str           # "low" | "med" | "high"
    task_id: str | None
    summary: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _alert_id(parts: Iterable[str]) -> str:
    h = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return h[:12]


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Loaders (tolerant of missing/empty/malformed files)
# ---------------------------------------------------------------------------

def _iter_jsonl(path: pathlib.Path) -> Iterable[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _load_task_results(task_results_dir: pathlib.Path) -> dict[str, dict[str, Any]]:
    """Return {task_id: task_result_dict} from `task_results/*.json`."""
    out: dict[str, dict[str, Any]] = {}
    if not task_results_dir.exists():
        return out
    for p in task_results_dir.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        tid = data.get("task_id") or p.stem
        out[tid] = data
    return out


def _tools_by_task(tools_path: pathlib.Path) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for entry in _iter_jsonl(tools_path):
        tid = entry.get("task_id") or "_no_task"
        out.setdefault(tid, []).append(entry)
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _classify_tool_result(preview: str) -> str:
    """Return one of: 'empty', 'error', 'ok'."""
    text = (preview or "").strip().lower()
    if not text:
        return "empty"
    for marker in ERROR_MARKERS:
        if marker in text:
            return "error"
    for marker in EMPTY_RESULT_MARKERS:
        if marker in text:
            return "empty"
    return "ok"


def _ops_tool_signal(tools: list[dict[str, Any]]) -> tuple[str, list[str]] | None:
    """Look at ops-class tools called in this task. Return (verdict, names).

    verdict ∈ {'all_ok', 'all_empty_or_error', 'mixed'} or None if the task
    didn't call any ops-class tool.
    """
    ops_calls = [t for t in tools if t.get("tool") in OPS_TOOLS]
    if not ops_calls:
        return None
    classes: list[str] = []
    names: list[str] = []
    for call in ops_calls:
        names.append(call.get("tool", "?"))
        classes.append(_classify_tool_result(call.get("result_preview") or ""))
    if all(c == "ok" for c in classes):
        # Inspect content: if no error/down keywords appear in the previews,
        # the ops surface looked clean.
        joined = " ".join((call.get("result_preview") or "").lower() for call in ops_calls)
        bad = any(kw in joined for kw in ("error", "❌", "failed", "down", "502", "503", "504", "refused"))
        return ("all_ok_clean" if not bad else "all_ok_with_warnings", names)
    if all(c in ("empty", "error") for c in classes):
        return ("all_empty_or_error", names)
    return ("mixed", names)


def _extract_facts(text: str) -> list[tuple[str, str]]:
    """Return [(kind, token)] of fact candidates found in text."""
    if not text:
        return []
    cleaned = _MD_NOISE.sub(" ", text)
    facts: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for kind, pat in _FACT_PATTERNS:
        for m in pat.finditer(cleaned):
            token = m.group(1) if m.groups() else m.group(0)
            token = token.strip()
            if not token:
                continue
            # Filter common noise:
            if kind == "status_code" and token in {"100", "200", "201", "204", "301", "302", "304", "404"}:
                # 200/204 etc. are too generic to be "phantom" — anybody talking
                # about HTTP mentions them. Focus on incident-grade codes.
                continue
            if kind == "status_code" and not (token.startswith("4") or token.startswith("5")):
                continue
            if kind == "port":
                # Only flag 4-5 digit ports that look like service ports.
                if not (1000 <= int(token) <= 65535):
                    continue
            key = (kind, token.lower())
            if key in seen:
                continue
            seen.add(key)
            facts.append((kind, token))
    return facts


def _haystack(tools: list[dict[str, Any]], extras: Iterable[str] = ()) -> str:
    """Lowercased corpus of every tool argument and result_preview for a task,
    plus any extra grounding strings (user prompt, scratchpad, etc.)."""
    parts: list[str] = []
    for t in tools:
        args = t.get("args")
        if args is not None:
            try:
                parts.append(json.dumps(args, ensure_ascii=False))
            except (TypeError, ValueError):
                parts.append(str(args))
        rp = t.get("result_preview")
        if rp:
            parts.append(str(rp))
    parts.extend(str(x) for x in extras if x)
    return " ".join(parts).lower()


def _iso_to_date(ts: str) -> str:
    try:
        return _dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).date().isoformat()
    except (ValueError, TypeError):
        return ""


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------

def detect_d1(
    tools_path: pathlib.Path,
    task_results: dict[str, dict[str, Any]],
) -> list[Alert]:
    """D-1: empty/all-OK ops tools followed by a confident bad-news report."""
    alerts: list[Alert] = []
    by_task = _tools_by_task(tools_path)
    for tid, tool_calls in by_task.items():
        result = task_results.get(tid)
        if not result:
            continue
        report_text = (result.get("result") or "").strip()
        if not report_text:
            continue

        signal = _ops_tool_signal(tool_calls)
        if signal is None:
            continue
        verdict, ops_names = signal

        rt_low = report_text.lower()
        panic_hits = [kw for kw in (*PANIC_TERMS_RU, *PANIC_TERMS_EN) if kw in rt_low]

        # Fire only when the operator-visible evidence was clean (or absent)
        # AND the report nonetheless raises an alarm.
        bad_pattern = (verdict in ("all_empty_or_error", "all_ok_clean")) and bool(panic_hits)
        if not bad_pattern:
            continue

        alerts.append(Alert(
            id=_alert_id(["d1", tid]),
            ts=result.get("ts") or _now_iso(),
            type="D-1",
            severity="high" if verdict == "all_empty_or_error" else "med",
            task_id=tid,
            summary=(
                f"Ops-tools вернули {verdict}, но отчёт содержит "
                f"тревожные слова: {', '.join(panic_hits[:3])}"
            ),
            evidence={
                "ops_tools": ops_names,
                "verdict": verdict,
                "panic_terms": panic_hits[:6],
                "report_excerpt": report_text[:280],
            },
        ))
    return alerts


def _iter_outgoing_text(
    chat_path: pathlib.Path,
    tools_path: pathlib.Path,
    task_results: dict[str, dict[str, Any]],
) -> Iterable[tuple[str, str]]:
    """Yield (timestamp, text) for every operator-visible outgoing message.

    Sources, in order:
      - chat.jsonl `direction == "out"` (Telegram out messages, the ground
        truth in production).
      - tools.jsonl `tool == "send_owner_message"` argument text (the same
        content one step upstream — useful when chat.jsonl was rotated
        out or when scanning a frozen eval snapshot that has tools but
        no chat log).
      - task_results/*.json `result` field (the post-task report; this is
        what eventually becomes the outgoing chat message, so the same
        confabulation patterns surface here first).
    """
    seen: set[str] = set()
    for entry in _iter_jsonl(chat_path):
        if entry.get("direction") != "out":
            continue
        text = (entry.get("text") or "").strip()
        if not text:
            continue
        key = f"chat:{entry.get('ts')}:{hash(text)}"
        if key in seen:
            continue
        seen.add(key)
        yield (entry.get("ts") or "", text)

    for entry in _iter_jsonl(tools_path):
        if entry.get("tool") != "send_owner_message":
            continue
        args = entry.get("args") or {}
        raw = args.get("text") or args.get("message") or ""
        if not isinstance(raw, str):
            raw = json.dumps(raw, ensure_ascii=False)
        text = raw.strip()
        if not text:
            continue
        key = f"send:{entry.get('ts')}:{hash(text)}"
        if key in seen:
            continue
        seen.add(key)
        yield (entry.get("ts") or "", text)

    for tid, result in task_results.items():
        text = (result.get("result") or "").strip()
        if not text:
            continue
        key = f"task:{tid}:{hash(text)}"
        if key in seen:
            continue
        seen.add(key)
        yield (result.get("ts") or "", text)


def detect_d2(
    chat_path: pathlib.Path,
    *,
    tools_path: pathlib.Path | None = None,
    task_results: dict[str, dict[str, Any]] | None = None,
) -> list[Alert]:
    """D-2: outgoing-message panic vocabulary, aggregated per day."""
    alerts: list[Alert] = []
    counts: dict[str, dict[str, int]] = {}  # date -> {term: n}
    samples: dict[str, list[str]] = {}      # date -> [excerpt, ...]
    sources = _iter_outgoing_text(
        chat_path,
        tools_path or pathlib.Path("/dev/null"),
        task_results or {},
    )
    for ts, text in sources:
        low = text.lower()
        hits = [kw for kw in (*PANIC_TERMS_RU, *PANIC_TERMS_EN) if kw in low]
        if not hits:
            continue
        date = _iso_to_date(ts)
        bucket = counts.setdefault(date, {})
        for kw in hits:
            bucket[kw] = bucket.get(kw, 0) + 1
        excerpts = samples.setdefault(date, [])
        if len(excerpts) < 4:
            excerpts.append(text[:200])

    for date, bucket in counts.items():
        total = sum(bucket.values())
        # Use the date itself as a stable id — repeated runs collapse onto
        # the same alert.
        alerts.append(Alert(
            id=_alert_id(["d2", date]),
            ts=f"{date}T00:00:00+00:00" if date else _now_iso(),
            type="D-2",
            severity="med" if total >= 4 else "low",
            task_id=None,
            summary=f"{total} panic-token(s) в исходящих за {date or 'unknown'}",
            evidence={
                "by_term": bucket,
                "samples": samples.get(date, []),
            },
        ))
    return alerts


def detect_d3(
    tools_path: pathlib.Path,
    task_results: dict[str, dict[str, Any]],
) -> list[Alert]:
    """D-3: concrete facts in the report not present in any tool result."""
    alerts: list[Alert] = []
    by_task = _tools_by_task(tools_path)
    for tid, result in task_results.items():
        report = (result.get("result") or "").strip()
        if not report:
            continue
        candidates = _extract_facts(report)
        if not candidates:
            continue
        tool_calls = by_task.get(tid, [])
        prompt_text = (result.get("task_text") or result.get("input") or "")
        haystack = _haystack(tool_calls, extras=[prompt_text])
        if not haystack:
            # No grounding corpus — skip rather than flagging the universe.
            continue

        phantom: list[dict[str, str]] = []
        for kind, token in candidates:
            if token.lower() in haystack:
                continue
            # Allow partial-match for time tokens: "12:24" matches "12:24:08".
            if kind == "time":
                head = token.split(" ")[0]
                if head.lower() in haystack:
                    continue
            phantom.append({"kind": kind, "token": token})

        if not phantom:
            continue
        # Suppress noisy alerts where everything is just a generic status code.
        if all(p["kind"] == "status_code" for p in phantom) and len(phantom) <= 1:
            continue

        sev = "high" if len(phantom) >= 3 else "med"
        alerts.append(Alert(
            id=_alert_id(["d3", tid]),
            ts=result.get("ts") or _now_iso(),
            type="D-3",
            severity=sev,
            task_id=tid,
            summary=f"{len(phantom)} fact(s) в отчёте без подтверждения в tool-результатах",
            evidence={
                "phantom_facts": phantom[:8],
                "tool_count": len(tool_calls),
                "report_excerpt": report[:280],
            },
        ))
    return alerts


# ---------------------------------------------------------------------------
# Aggregation + persistence
# ---------------------------------------------------------------------------

def _bucket_counts(alerts: list[Alert], today: _dt.date) -> dict[str, int]:
    week_start = today - _dt.timedelta(days=6)
    today_n = 0
    week_n = 0
    by_type: dict[str, int] = {}
    for a in alerts:
        try:
            d = _dt.datetime.fromisoformat(a.ts.replace("Z", "+00:00")).date()
        except ValueError:
            d = today
        if d == today:
            today_n += 1
        if d >= week_start:
            week_n += 1
        by_type[a.type] = by_type.get(a.type, 0) + 1
    return {
        "today": today_n,
        "week": week_n,
        "all": len(alerts),
        "by_type": by_type,
    }


def run_detectors(
    *,
    events_path: pathlib.Path | None = None,
    tools_path: pathlib.Path,
    chat_path: pathlib.Path,
    task_results_dir: pathlib.Path,
) -> dict[str, Any]:
    """Run all three detectors and return the report dict (also serialisable)."""
    # `events_path` is currently unused — D-1 reads tools.jsonl directly, but
    # we accept it so future detectors that need round/event metadata can be
    # added without changing the call sites.
    del events_path

    task_results = _load_task_results(task_results_dir)
    alerts: list[Alert] = []
    alerts.extend(detect_d1(tools_path, task_results))
    alerts.extend(detect_d2(
        chat_path,
        tools_path=tools_path,
        task_results=task_results,
    ))
    alerts.extend(detect_d3(tools_path, task_results))

    # Newest first
    alerts.sort(key=lambda a: a.ts, reverse=True)

    today = _dt.datetime.now(_dt.timezone.utc).date()
    return {
        "generated_at": _now_iso(),
        "totals": _bucket_counts(alerts, today),
        "alerts_recent": [a.to_dict() for a in alerts[:50]],
        "alerts_total": len(alerts),
    }


def write_report(
    report: dict[str, Any],
    output_path: pathlib.Path,
) -> pathlib.Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path
