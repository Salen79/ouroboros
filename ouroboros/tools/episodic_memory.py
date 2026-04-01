"""
Episodic Memory tools for THAI.

Tools:
1. memory_search — search episodic memory by keywords/tags
2. record_memory — record a new entry to episodic memory
3. save_skill — save a learned procedure/skill
4. find_skills — search for learned skills
5. recent_session — show recent activity summary (chat + episodic) for last N hours
"""

from __future__ import annotations

import json
import logging
import pathlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from ouroboros.tools.registry import ToolContext, ToolEntry

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


def _tool_memory_search(ctx: ToolContext, query: str, days: int = 60, limit: int = 10, **kwargs) -> str:
    """Search episodic memory for relevant entries."""
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
    ctx: ToolContext,
    title: str,
    content: str,
    type: str = "insight",
    tags: List[str] = None,
    importance: int = 3,
    **kwargs,
) -> str:
    """Record an important memory to the episodic layer."""
    if not title or not title.strip():
        return "⚠️ title is required"
    if not content or not content.strip():
        return "⚠️ content is required"

    valid_types = {"insight", "decision", "conversation", "milestone", "error_pattern", "skill"}
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

    # Sync to ChromaDB (best-effort, JSONL remains source of truth)
    try:
        from ouroboros.tools.semantic_memory import upsert_episode
        upsert_episode(entry)
    except Exception as e:
        log.debug("ChromaDB sync failed (non-critical): %s", e)

    stars = "★" * importance
    tag_str = " ".join(f"#{t}" for t in tags) if tags else "(no tags)"
    return f"✅ Memory recorded [{type}] {stars}\nTitle: {title}\nTags: {tag_str}\nFile: {ep_file.name}"


def _tool_save_skill(
    ctx: ToolContext,
    name: str,
    description: str,
    steps: List[str] = None,
    tools_used: List[str] = None,
    pitfalls: List[str] = None,
    **kwargs,
) -> str:
    """Save a learned procedure/skill to episodic memory.

    Use after completing a multi-step task successfully to remember how to do it next time.
    """
    if not name or not name.strip():
        return "⚠️ name is required"
    if not description or not description.strip():
        return "⚠️ description is required"

    if steps is None:
        steps = []
    if tools_used is None:
        tools_used = []
    if pitfalls is None:
        pitfalls = []

    content_parts = [description.strip()]
    if steps:
        content_parts.append("\nSteps:\n" + "\n".join(f"  {i+1}. {s}" for i, s in enumerate(steps)))
    if tools_used:
        content_parts.append("\nTools used: " + ", ".join(tools_used))
    if pitfalls:
        content_parts.append("\nPitfalls:\n" + "\n".join(f"  - {p}" for p in pitfalls))

    return _tool_record_memory(
        ctx=ctx,
        title=f"SKILL: {name.strip()}",
        content="\n".join(content_parts),
        type="skill",
        tags=["skill"] + tools_used[:5],
        importance=4,
    )


def _tool_find_skills(ctx: ToolContext, query: str, limit: int = 3, **kwargs) -> str:
    """Search for learned skills/procedures in episodic memory.

    Searches only skill-type entries from the last 365 days.
    """
    if not query or not query.strip():
        return "⚠️ query is required"

    query_terms = re.split(r'[\s,;]+', query.strip())
    query_terms = [t for t in query_terms if len(t) >= 2]

    if not query_terms:
        return "⚠️ query must contain at least one term"

    entries = _read_episodic_entries(days=365)
    # Filter to skill-type only
    entries = [e for e in entries if e.get("type") == "skill"]

    if not entries:
        return "No skills found in episodic memory."

    scored = [(e, _score_entry(e, query_terms)) for e in entries]
    scored = [(e, s) for e, s in scored if s > 0]
    scored.sort(key=lambda x: x[1], reverse=True)

    if not scored:
        return f"No skills matching '{query}'"

    top = scored[:limit]
    lines = [f"Found {len(scored)} matching skills (showing top {len(top)}):\n"]
    for i, (entry, score) in enumerate(top, 1):
        lines.append(f"--- {i}. (relevance: {score}) ---")
        lines.append(_format_entry(entry))
        lines.append("")

    return "\n".join(lines)


def _tool_recent_session(ctx: ToolContext, hours: int = 2, **kwargs) -> str:
    """Show recent activity summary — chat messages and episodic entries from last N hours."""
    hours = max(1, min(48, int(hours)))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    sections: List[str] = []

    # --- Chat log ---
    chat_path = _get_drive_root() / "logs" / "chat.jsonl"
    chat_lines: List[str] = []
    if chat_path.exists():
        try:
            for line in chat_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts_str = entry.get("ts", "")
                    if not ts_str:
                        continue
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue
                    hhmm = ts.strftime("%H:%M")
                    role = entry.get("role", "?")
                    content = entry.get("content", "")
                    snippet = content[:100].replace("\n", " ")
                    if len(content) > 100:
                        snippet += "…"
                    chat_lines.append(f"[{hhmm}] {role}: {snippet}")
                except (json.JSONDecodeError, ValueError):
                    continue
        except OSError as e:
            sections.append(f"⚠️ Could not read chat log: {e}")

        if chat_lines:
            # Keep last 30 messages
            if len(chat_lines) > 30:
                chat_lines = chat_lines[-30:]
                sections.append(f"📨 Chat (last 30 of more messages):\n" + "\n".join(chat_lines))
            else:
                sections.append(f"📨 Chat ({len(chat_lines)} messages):\n" + "\n".join(chat_lines))
    elif not chat_path.exists():
        sections.append("(chat.jsonl not found — no chat history available)")

    # --- Episodic entries ---
    ep_entries: List[str] = []
    try:
        all_entries = _read_episodic_entries(days=max(1, (hours // 24) + 1))
        for entry in all_entries:
            ts_str = entry.get("ts", "")
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts < cutoff:
                    continue
            except ValueError:
                continue
            hhmm = ts.strftime("%H:%M")
            entry_type = entry.get("type", "?")
            title = entry.get("title", "(no title)")
            ep_entries.append(f"[{hhmm}] {entry_type}: {title}")
    except Exception as e:
        sections.append(f"⚠️ Could not read episodic memory: {e}")

    if ep_entries:
        # Keep last 5
        shown = ep_entries[-5:] if len(ep_entries) > 5 else ep_entries
        sections.append(f"🧠 Episodic entries ({len(ep_entries)} total, showing last {len(shown)}):\n" + "\n".join(shown))

    if not chat_lines and not ep_entries and len(sections) == 0:
        return f"(no activity in last {hours} hours)"

    # If we only have error messages but no actual data
    if not chat_lines and not ep_entries:
        sections.append(f"(no activity in last {hours} hours)")

    header = f"=== Recent session summary (last {hours}h) ==="
    return header + "\n\n" + "\n\n".join(sections)


def get_tools() -> List[ToolEntry]:
    """Return tool definitions for episodic memory."""
    return [
        ToolEntry(
            name="memory_search",
            schema={
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
            },
            handler=_tool_memory_search,
        ),
        ToolEntry(
            name="record_memory",
            schema={
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
                            "enum": ["insight", "decision", "conversation", "milestone", "error_pattern", "skill"],
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
            },
            handler=_tool_record_memory,
        ),
        ToolEntry(
            name="save_skill",
            schema={
                "name": "save_skill",
                "description": (
                    "Save a learned procedure/skill to episodic memory. "
                    "Use after completing a multi-step task successfully to remember "
                    "how to do it next time. Wraps record_memory with type='skill'."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Short skill name (e.g. 'deploy-prism', 'fix-registry-crash')"
                        },
                        "description": {
                            "type": "string",
                            "description": "What this skill does and when to use it"
                        },
                        "steps": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Ordered list of steps to execute"
                        },
                        "tools_used": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tools involved (e.g. ['claude_code_edit', 'run_shell'])"
                        },
                        "pitfalls": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Known pitfalls and things to avoid"
                        }
                    },
                    "required": ["name", "description"]
                },
            },
            handler=_tool_save_skill,
        ),
        ToolEntry(
            name="find_skills",
            schema={
                "name": "find_skills",
                "description": (
                    "Search for learned skills/procedures in episodic memory. "
                    "Use BEFORE starting a task to check if a similar procedure was already learned. "
                    "Searches only skill-type entries from the last 365 days."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search terms — skill name, tools, or task description"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max skills to return (default: 3)",
                            "default": 3
                        }
                    },
                    "required": ["query"]
                },
            },
            handler=_tool_find_skills,
        ),
        ToolEntry(
            name="recent_session",
            schema={
                "name": "recent_session",
                "description": (
                    "Show recent activity summary — what was discussed and done in the last N hours. "
                    "Use after /panic restart to quickly catch up on context without re-running diagnostics."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "hours": {
                            "type": "integer",
                            "description": "How many hours back to look",
                            "default": 2
                        }
                    },
                    "required": []
                },
            },
            handler=_tool_recent_session,
        ),
    ]
