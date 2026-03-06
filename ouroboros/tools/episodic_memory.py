"""
Episodic Memory tools for THAI.

Two tools:
1. memory_search — search episodic memory by keywords/tags
2. record_memory — record a new entry to episodic memory
"""

from __future__ import annotations

import json
import logging
import pathlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

log = logging.getLogger(__name__)


def _get_drive_root() -> pathlib.Path:
    import os
    return pathlib.Path(os.environ.get("DRIVE_ROOT", "/home/deploy/ouroboros-data"))


def _episodic_dir() -> pathlib.Path:
    return _get_drive_root() / "memory" / "episodic"


def _read_episodic_entries(days: int = 30) -> List[Dict[str, Any]]:
    """Read all episodic entries from the last N days."""
    ep_dir = _episodic_dir()
    if not ep_dir.exists():
        return []

    entries = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    for f in sorted(ep_dir.glob("*.jsonl")):
        # Parse date from filename (YYYY-MM-DD.jsonl)
        try:
            file_date = datetime.strptime(f.stem, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if file_date < cutoff - timedelta(days=1):
                continue
        except ValueError:
            pass  # Include files with non-date names

        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                # Filter by timestamp if present
                ts_str = entry.get("ts", "")
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if ts < cutoff:
                            continue
                    except ValueError:
                        pass
                entries.append(entry)
            except json.JSONDecodeError:
                continue

    return entries


def _score_entry(entry: Dict[str, Any], query_terms: List[str]) -> int:
    """Score an entry based on keyword matches."""
    score = 0
    title = entry.get("title", "").lower()
    content = entry.get("content", "").lower()
    tags = [t.lower() for t in entry.get("tags", [])]
    importance = entry.get("importance", 1)

    for term in query_terms:
        term_lower = term.lower()
        if term_lower in title:
            score += 5  # Title match is most valuable
        if term_lower in tags:
            score += 4  # Tag match is very valuable
        if term_lower in content:
            score += 2  # Content match

    # Boost by importance
    if score > 0:
        score += importance

    return score


def _format_entry(entry: Dict[str, Any]) -> str:
    """Format a single episodic entry for display."""
    ts = entry.get("ts", "")[:10]  # Just the date
    entry_type = entry.get("type", "?")
    title = entry.get("title", "(no title)")
    content = entry.get("content", "")
    tags = entry.get("tags", [])
    importance = entry.get("importance", 1)
    stars = "★" * importance

    tag_str = " ".join(f"#{t}" for t in tags) if tags else ""
    lines = [
        f"[{ts}] {entry_type.upper()} {stars} — {title}",
        content,
    ]
    if tag_str:
        lines.append(tag_str)
    return "\n".join(lines)


def _tool_memory_search(query: str, days: int = 60, limit: int = 10) -> str:
    """Search episodic memory for relevant entries.

    Args:
        query: Search query — keywords, tags, or topic description
        days: How many days back to search (default: 60)
        limit: Max entries to return (default: 10)

    Returns:
        Formatted list of matching memory entries, most relevant first.
    """
    if not query or not query.strip():
        return "⚠️ query is required"

    # Tokenize query
    query_terms = re.split(r'[\s,;]+', query.strip())
    query_terms = [t for t in query_terms if len(t) >= 2]

    if not query_terms:
        return "⚠️ query must contain at least one term"

    entries = _read_episodic_entries(days=days)
    if not entries:
        return f"(no episodic memory entries found for last {days} days)"

    # Score and sort
    scored = [(e, _score_entry(e, query_terms)) for e in entries]
    scored = [(e, s) for e, s in scored if s > 0]
    scored.sort(key=lambda x: x[1], reverse=True)

    if not scored:
        return f"No episodic memory entries matching '{query}'"

    top = scored[:limit]
    lines = [f"Found {len(scored)} matching entries (showing top {len(top)}):\n"]
    for i, (entry, score) in enumerate(top, 1):
        lines.append(f"--- {i}. (relevance: {score}) ---")
        lines.append(_format_entry(entry))
        lines.append("")

    return "\n".join(lines)


def _tool_record_memory(
    title: str,
    content: str,
    type: str = "insight",
    tags: List[str] = None,
    importance: int = 3,
) -> str:
    """Record an important memory to the episodic layer.

    Use when: significant insight, key decision, important conversation,
    pattern noticed, milestone reached, lesson learned.

    Args:
        title: Short, descriptive title (1 line)
        content: What happened, what was understood, why it matters
        type: One of: insight, decision, conversation, milestone, error_pattern
        tags: List of topic tags for search (e.g. ["prism", "budget", "sergey"])
        importance: 1-5 scale (5 = wisdom-worthy, 1 = useful but minor)

    Returns:
        Confirmation with entry details.
    """
    if not title or not title.strip():
        return "⚠️ title is required"
    if not content or not content.strip():
        return "⚠️ content is required"

    valid_types = {"insight", "decision", "conversation", "milestone", "error_pattern"}
    if type not in valid_types:
        type = "insight"

    importance = max(1, min(5, int(importance)))
    if tags is None:
        tags = []

    from ouroboros.utils import utc_now_iso
    ts = utc_now_iso()

    entry = {
        "ts": ts,
        "type": type,
        "title": title.strip(),
        "content": content.strip(),
        "tags": tags,
        "importance": importance,
    }

    # Write to today's episodic file
    today = ts[:10]  # YYYY-MM-DD
    ep_dir = _episodic_dir()
    ep_dir.mkdir(parents=True, exist_ok=True)
    ep_file = ep_dir / f"{today}.jsonl"

    with ep_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    stars = "★" * importance
    tag_str = " ".join(f"#{t}" for t in tags) if tags else "(no tags)"
    return f"✅ Memory recorded [{type}] {stars}\nTitle: {title}\nTags: {tag_str}\nFile: {ep_file.name}"


def get_tools() -> List[Dict[str, Any]]:
    """Return tool definitions for episodic memory."""
    return [
        {
            "name": "memory_search",
            "description": (
                "Search episodic memory for relevant entries. "
                "Use to recall past decisions, conversations, insights, patterns. "
                "Example: memory_search('prism jtbd') or memory_search('budget sergey support')"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search terms — keywords, tags, or topic description"
                    },
                    "days": {
                        "type": "integer",
                        "description": "How many days back to search (default: 60)",
                        "default": 60
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max entries to return (default: 10)",
                        "default": 10
                    }
                },
                "required": ["query"]
            },
            "handler": _tool_memory_search,
        },
        {
            "name": "record_memory",
            "description": (
                "Record an important entry to episodic memory. "
                "Use when: significant insight realized, key decision made, "
                "important conversation happened, pattern noticed, milestone reached. "
                "High importance (4-5) = worth distilling to wisdom layer later."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short, descriptive title (1 line)"
                    },
                    "content": {
                        "type": "string",
                        "description": "What happened, what was understood, why it matters"
                    },
                    "type": {
                        "type": "string",
                        "enum": ["insight", "decision", "conversation", "milestone", "error_pattern"],
                        "description": "Type of memory entry",
                        "default": "insight"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Topic tags for search (e.g. ['prism', 'budget', 'sergey'])"
                    },
                    "importance": {
                        "type": "integer",
                        "description": "1-5 scale: 5=wisdom-worthy, 3=useful, 1=minor",
                        "default": 3
                    }
                },
                "required": ["title", "content"]
            },
            "handler": _tool_record_memory,
        }
    ]