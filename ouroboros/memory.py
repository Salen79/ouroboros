"""
Ouroboros — Memory.

Scratchpad, identity, chat history.
Contract: load scratchpad/identity, chat_history().
"""

from __future__ import annotations

import datetime
import json
import logging
import pathlib
from collections import Counter
from typing import Any, Dict, List, Optional

from ouroboros.utils import utc_now_iso, read_text, write_text, append_jsonl, short

log = logging.getLogger(__name__)


class Memory:
    """Ouroboros memory management: scratchpad, identity, chat history, logs."""

    def __init__(self, drive_root: pathlib.Path, repo_dir: Optional[pathlib.Path] = None):
        self.drive_root = drive_root
        self.repo_dir = repo_dir

    # --- Paths ---

    def _memory_path(self, rel: str) -> pathlib.Path:
        return (self.drive_root / "memory" / rel).resolve()

    def scratchpad_path(self) -> pathlib.Path:
        return self._memory_path("scratchpad.md")

    def identity_path(self) -> pathlib.Path:
        return self._memory_path("identity.md")

    def journal_path(self) -> pathlib.Path:
        return self._memory_path("scratchpad_journal.jsonl")

    def logs_path(self, name: str) -> pathlib.Path:
        return (self.drive_root / "logs" / name).resolve()

    # --- Load / save ---

    def load_scratchpad(self) -> str:
        p = self.scratchpad_path()
        if p.exists():
            return read_text(p)
        default = self._default_scratchpad()
        write_text(p, default)
        return default

    def save_scratchpad(self, content: str) -> None:
        write_text(self.scratchpad_path(), content)

    def load_identity(self) -> str:
        p = self.identity_path()
        if p.exists():
            return read_text(p)
        default = self._default_identity()
        write_text(p, default)
        return default

    def ensure_files(self) -> None:
        """Create memory files if they don't exist."""
        if not self.scratchpad_path().exists():
            write_text(self.scratchpad_path(), self._default_scratchpad())
        if not self.identity_path().exists():
            write_text(self.identity_path(), self._default_identity())
        if not self.journal_path().exists():
            write_text(self.journal_path(), "")

    # --- Chat history ---

    def chat_history(self, count: int = 100, offset: int = 0, search: str = "") -> str:
        """Read from logs/chat.jsonl and logs/events.jsonl. count messages, offset from end, filter by search."""
        chat_path = self.logs_path("chat.jsonl")
        events_path = self.logs_path("events.jsonl")
        
        message_entries = []
        if chat_path.exists():
            try:
                raw_lines = chat_path.read_text(encoding="utf-8").strip().split("\n")
                for line in raw_lines:
                    line = line.strip()
                    if not line: continue
                    try:
                        entry = json.loads(line)
                        entry["source"] = "chat" # Mark source
                        message_entries.append(entry)
                    except Exception:
                        log.debug(f"Failed to parse JSON line in chat_history: {line[:100]}")
            except Exception as e:
                log.warning(f"Failed to read chat.jsonl: {e}")

        event_entries = []
        if events_path.exists():
            try:
                raw_lines = events_path.read_text(encoding="utf-8").strip().split("\n")
                for line in raw_lines:
                    line = line.strip()
                    if not line: continue
                    try:
                        entry = json.loads(line)
                        entry["source"] = "event" # Mark source
                        event_entries.append(entry)
                    except Exception:
                        log.debug(f"Failed to parse JSON line in events.jsonl: {line[:100]}")
            except Exception as e:
                log.warning(f"Failed to read events.jsonl: {e}")
        
        # Combine and sort by timestamp
        all_entries = message_entries + event_entries
        all_entries.sort(key=lambda x: x.get("ts", "")) # Sort by timestamp

        if search:
            search_lower = search.lower()
            all_entries = [e for e in all_entries if search_lower in str(e).lower()]

        if offset > 0:
            all_entries = all_entries[:-offset] if offset < len(all_entries) else []

        all_entries = all_entries[-count:] if count < len(all_entries) else all_entries

        if not all_entries:
            return "(no messages or events matching query)"

        lines = []
        for e in all_entries:
            source = e.get("source")
            ts_full = e.get("ts", "")
            ts_hhmm = ts_full[11:16] if ts_full and len(ts_full) >= 16 else ""

            if source == "chat":
                dir_raw = str(e.get("direction", "")).lower()
                direction = "→" if dir_raw in ("out", "outgoing") else "←"
                raw_text = str(e.get("text", ""))
                if dir_raw in ("out", "outgoing"):
                    text = short(raw_text, 800)
                else:
                    text = raw_text  # never truncate creator's messages
                lines.append(f"{direction} [{ts_hhmm}] {text}")
            elif source == "event":
                evt_type = e.get("type", "?")
                event_text = short(str(e.get("text", e.get("error", ""))), 700) # Show text or error
                lines.append(f"⚙️ [{ts_hhmm}] {evt_type}: {event_text}")
            else: # Fallback for unknown sources
                lines.append(f"❓ [{ts_hhmm}] {short(str(e), 700)}")

        return f"Showing {len(lines)} recent messages/events:\n\n" + "\n".join(lines)


    # --- JSONL tail reading ---

    def read_jsonl_tail(self, log_name: str, max_entries: int = 100) -> List[Dict[str, Any]]:
        """Read the last max_entries records from a JSONL file."""
        path = self.logs_path(log_name)
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8").strip().split("\n")
            tail = lines[-max_entries:] if max_entries < len(lines) else lines
            entries = []
            for line in tail:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    log.debug(f"Failed to parse JSON line in read_jsonl_tail: {line[:100]}", exc_info=True)
                    continue
            return entries
        except Exception:
            log.warning(f"Failed to read JSONL tail from {log_name}", exc_info=True)
            return []

    # --- Log summarization ---

    def summarize_chat(self, entries: List[Dict[str, Any]]) -> str:
        if not entries:
            return ""
        lines = []
        for e in entries[-100:]:
            if e.get("source") == "chat":
                dir_raw = str(e.get("direction", "")).lower()
                direction = "→" if dir_raw in ("out", "outgoing") else "←"
                ts_full = e.get("ts", "")
                ts_hhmm = ts_full[11:16] if ts_full and len(ts_full) >= 16 else ""

                raw_text = str(e.get("text", ""))
                if dir_raw in ("out", "outgoing"):
                    text = short(raw_text, 800)
                else:
                    text = raw_text  # never truncate creator's messages
                lines.append(f"{direction} {ts_hhmm} {text}")
            elif e.get("source") == "event":
                ts_full = e.get("ts", "")
                ts_hhmm = ts_full[11:16] if ts_full and len(ts_full) >= 16 else ""
                evt_type = e.get("type", "?")
                event_text = short(str(e.get("text", e.get("error", ""))), 700)
                lines.append(f"⚙️ {ts_hhmm} {evt_type}: {event_text}")
            else:
                 ts_full = e.get("ts", "")
                 ts_hhmm = ts_full[11:16] if ts_full and len(ts_full) >= 16 else ""
                 lines.append(f"❓ {ts_hhmm}: {short(str(e), 700)}")
        return "\n".join(lines)

    def summarize_progress(self, entries: List[Dict[str, Any]], limit: int = 15) -> str:
        """Summarize progress.jsonl entries (Ouroboros's self-talk / progress messages)."""
        if not entries:
            return ""
        lines = []
        for e in entries[-limit:]:
            ts_full = e.get("ts", "")
            ts_hhmm = ts_full[11:16] if ts_full and len(ts_full) >= 16 else ""
            text = short(str(e.get("text", "")), 300)
            lines.append(f"⚙️ {ts_hhmm} {text}")
        return "\n".join(lines)

    def summarize_tools(self, entries: List[Dict[str, Any]]) -> str:
        if not entries:
            return ""
        lines = []
        for e in entries[-10:]:
            tool = e.get("tool") or e.get("tool_name") or "?"
            args = e.get("args", {})
            hints = []
            for key in ("path", "dir", "commit_message", "query"):
                if key in args:
                    hints.append(f"{key}={short(str(args[key]), 60)}")
            if "cmd" in args:
                hints.append(f"cmd={short(str(args['cmd']), 80)}")
            hint_str = ", ".join(hints) if hints else ""
            status = "✓" if ("result_preview" in e and not str(e.get("result_preview", "")).lstrip().startswith("⚠️")) else "·"
            lines.append(f"{status} {tool} {hint_str}".strip())
        return "\n".join(lines)

    def summarize_events(self, entries: List[Dict[str, Any]]) -> str:
        if not entries:
            return ""
        type_counts: Counter = Counter()
        for e in entries:
            type_counts[e.get("type", "unknown")] += 1
        top_types = type_counts.most_common(10)
        lines = ["Event counts:"]
        for evt_type, count in top_types:
            lines.append(f"  {evt_type}: {count}")
        error_types = {"tool_error", "telegram_api_error", "task_error", "tool_rounds_exceeded"}
        errors = [e for e in entries if e.get("type") in error_types]
        if errors:
            lines.append("\nRecent errors:")
            for e in errors[-10:]:
                lines.append(f"  {e.get('type', '?')}: {short(str(e.get('error', '')), 120)}")
        return "\n".join(lines)

    def summarize_supervisor(self, entries: List[Dict[str, Any]]) -> str:
        if not entries:
            return ""
        for e in reversed(entries):
            if e.get("type") in ("launcher_start", "restart", "boot"):
                branch = e.get("branch") or e.get("git_branch") or "?"
                sha = short(str(e.get("sha") or e.get("git_sha") or ""), 12)
                return f"{e['type']}: {e.get('ts', '')} branch={branch} sha={sha}"
        return ""

    def append_journal(self, entry: Dict[str, Any]) -> None:
        append_jsonl(self.journal_path(), entry)

    # --- Chat backup ---

    def backup_chat_to_drive(self) -> Dict[str, Any]:
        """Backup chat.jsonl to drive and create a dated milestone snapshot.

        Returns {"lines": N, "size_bytes": N, "milestone_created": bool}.
        If Drive write fails, logs the error and continues without crashing.
        """
        source_path = self.logs_path("chat.jsonl")
        if not source_path.exists():
            log.warning("backup_chat_to_drive: chat.jsonl not found at %s", source_path)
            return {"lines": 0, "size_bytes": 0, "milestone_created": False}

        try:
            content_bytes = source_path.read_bytes()
            size_bytes = len(content_bytes)
            text = content_bytes.decode("utf-8")
            lines = sum(1 for l in text.splitlines() if l.strip())
        except Exception as e:
            log.error("backup_chat_to_drive: failed to read chat.jsonl: %s", e)
            return {"lines": 0, "size_bytes": 0, "milestone_created": False}

        # Write main backup to drive path logs/chat.jsonl (overwrite)
        try:
            dest = (self.drive_root / "logs" / "chat.jsonl").resolve()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content_bytes)
        except Exception as e:
            log.error("backup_chat_to_drive: failed to write drive backup: %s", e)

        # Create dated milestone snapshot (only if one doesn't exist for today)
        milestone_created = False
        try:
            today = datetime.date.today().isoformat()  # e.g. "2026-03-05"
            milestone_path = (
                self.drive_root / "logs" / "milestones" / f"chat_{today}.jsonl"
            ).resolve()
            if not milestone_path.exists():
                milestone_path.parent.mkdir(parents=True, exist_ok=True)
                milestone_path.write_bytes(content_bytes)
                milestone_created = True
                log.info("backup_chat_to_drive: milestone created at %s", milestone_path)
        except Exception as e:
            log.error("backup_chat_to_drive: failed to create milestone: %s", e)

        return {"lines": lines, "size_bytes": size_bytes, "milestone_created": milestone_created}

    # --- Defaults ---

    def _default_scratchpad(self) -> str:
        return f"# Scratchpad\n\nUpdatedAt: {utc_now_iso()}\n\n(empty — write anything here)\n"

    def _default_identity(self) -> str:
        return (
            "# Who I Am\n\n"
            "I am Ouroboros. This file is my persistent self-identification.\n"
            "I can write anything here: how I see myself, how I want to communicate,\n"
            "what matters to me, what I have understood about myself.\n\n"
            "This file is read at every dialogue and influences my responses.\n"
            "I update it when I feel the need, via drive_write.\n"
        )


# ---------------------------------------------------------------------------
# Shareholder Directive Extraction & Persistence
# ---------------------------------------------------------------------------

_DIRECTIVE_TRIGGERS_RU = [
    "останови", "не трогай", "забудь", "отложи", "прекрати",
    "не делай", "пауза", "стоп", "хватит", "не надо",
]
_DIRECTIVE_TRIGGERS_EN = [
    "stop", "don't", "forget", "pause", "halt",
    "do not", "skip", "abandon", "drop",
]
_DIRECTIVE_TRIGGERS = _DIRECTIVE_TRIGGERS_RU + _DIRECTIVE_TRIGGERS_EN


def extract_directive(message: str) -> Optional[str]:
    """Check if a Shareholder message contains a directive.
    Returns the directive text if found, None otherwise."""
    lower = message.lower()
    for trigger in _DIRECTIVE_TRIGGERS:
        if trigger in lower:
            return message.strip()[:300]
    return None


def save_directive(directive: str, state_dir: pathlib.Path) -> None:
    """Save a directive to persistent storage with 24h expiry."""
    directives_path = state_dir / "directives.json"
    directives: list = []
    if directives_path.exists():
        try:
            directives = json.loads(directives_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            directives = []

    directives.append({
        "text": directive,
        "created_at": datetime.datetime.now().isoformat(),
        "expires_at": (datetime.datetime.now() + datetime.timedelta(hours=24)).isoformat(),
    })

    # Keep only last 10 directives
    directives = directives[-10:]
    directives_path.write_text(
        json.dumps(directives, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_active_directives(state_dir: pathlib.Path) -> list:
    """Load directives that haven't expired."""
    directives_path = state_dir / "directives.json"
    if not directives_path.exists():
        return []

    try:
        directives = json.loads(directives_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, Exception):
        return []

    now = datetime.datetime.now()
    active = []
    for d in directives:
        try:
            expires = datetime.datetime.fromisoformat(d["expires_at"])
            if now < expires:
                active.append(d)
        except (KeyError, ValueError):
            continue
    return active
