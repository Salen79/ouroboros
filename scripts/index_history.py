#!/usr/bin/env python3
"""
One-time indexing script: backfill episodic memory + chat/events into ChromaDB.

Usage:
    python scripts/index_history.py

Collections created:
    - thai_episodes: all episodic memory entries
    - thai_skills: skill-type episodic entries
    - thai_history: chat sessions + event task lifecycles
"""

import json
import os
import pathlib
import sys
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

DRIVE_ROOT = pathlib.Path(os.environ.get("DRIVE_ROOT", "/home/deploy/ouroboros-data"))
EPISODIC_DIR = DRIVE_ROOT / "memory" / "episodic"
CHAT_PATH = DRIVE_ROOT / "logs" / "chat.jsonl"
EVENTS_PATH = DRIVE_ROOT / "logs" / "events.jsonl"


def get_client():
    import chromadb
    client = chromadb.HttpClient(host="localhost", port=8000)
    client.heartbeat()
    return client


def index_episodic(client):
    """Backfill all JSONL files from episodic/ into thai_episodes + thai_skills."""
    from ouroboros.tools.semantic_memory import upsert_episode

    if not EPISODIC_DIR.exists():
        print(f"  No episodic dir at {EPISODIC_DIR}")
        return 0, 0

    ep_count = 0
    skill_count = 0

    for f in sorted(EPISODIC_DIR.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if upsert_episode(entry, client=client):
                ep_count += 1
                if entry.get("type") == "skill":
                    skill_count += 1

    return ep_count, skill_count


def index_chat(client):
    """Index chat.jsonl into thai_history, chunked by conversation sessions (gap > 30 min)."""
    from ouroboros.tools.semantic_memory import upsert_history_chunk

    if not CHAT_PATH.exists():
        print(f"  No chat file at {CHAT_PATH}")
        return 0

    messages = []
    with open(CHAT_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not messages:
        return 0

    # Split into sessions by 30-min gaps
    sessions = []
    current_session = [messages[0]]

    for msg in messages[1:]:
        prev_ts = current_session[-1].get("ts", "")
        curr_ts = msg.get("ts", "")

        try:
            prev_dt = datetime.fromisoformat(prev_ts.replace("Z", "+00:00"))
            curr_dt = datetime.fromisoformat(curr_ts.replace("Z", "+00:00"))
            gap_minutes = (curr_dt - prev_dt).total_seconds() / 60.0
        except (ValueError, TypeError):
            gap_minutes = 0

        if gap_minutes > 30:
            sessions.append(current_session)
            current_session = [msg]
        else:
            current_session.append(msg)

    if current_session:
        sessions.append(current_session)

    count = 0
    for i, session in enumerate(sessions):
        # Build session text
        lines = []
        for msg in session:
            direction = msg.get("direction", "?")
            speaker = "THAI" if direction == "out" else "Sergey"
            text = msg.get("text", "")
            if text:
                lines.append(f"{speaker}: {text[:500]}")

        if not lines:
            continue

        session_text = "\n".join(lines)
        # Truncate to ~2000 chars for embedding
        if len(session_text) > 2000:
            session_text = session_text[:2000] + "..."

        first_ts = session[0].get("ts", "")
        last_ts = session[-1].get("ts", "")
        date = first_ts[:10] if first_ts else ""

        doc_id = f"chat_session_{i}_{date}"
        metadata = {
            "type": "chat",
            "date": date,
            "ts_start": first_ts,
            "ts_end": last_ts,
            "msg_count": len(session),
        }

        if upsert_history_chunk(doc_id, session_text, metadata, client=client):
            count += 1

    return count


def index_events(client):
    """Index events.jsonl into thai_history, grouped by task_id."""
    from ouroboros.tools.semantic_memory import upsert_history_chunk

    if not EVENTS_PATH.exists():
        print(f"  No events file at {EVENTS_PATH}")
        return 0

    # Group events by task_id where available, otherwise by type
    task_events = {}  # task_id -> list of events
    standalone_events = []  # events without task_id

    with open(EVENTS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue

            task_id = ev.get("task_id")
            if task_id:
                task_events.setdefault(task_id, []).append(ev)
            else:
                # Only index meaningful standalone events
                ev_type = ev.get("type", "")
                if ev_type in ("consciousness_thought", "ops_incident", "proactive_message",
                               "task_eval", "startup_verification"):
                    standalone_events.append(ev)

    count = 0

    # Index task lifecycles
    for task_id, events in task_events.items():
        lines = []
        first_ts = events[0].get("ts", "")
        last_ts = events[-1].get("ts", "")

        for ev in events:
            ev_type = ev.get("type", "?")
            ts = ev.get("ts", "")[:16]
            cost = ev.get("cost_usd", "")
            desc = ev.get("description", "")
            error = ev.get("error", "")

            parts = [f"[{ts}] {ev_type}"]
            if desc:
                parts.append(f"desc={desc[:200]}")
            if cost:
                parts.append(f"cost=${cost}")
            if error:
                parts.append(f"error={error[:200]}")
            lines.append(" ".join(parts))

        text = "\n".join(lines)
        if len(text) > 2000:
            text = text[:2000] + "..."

        date = first_ts[:10] if first_ts else ""
        doc_id = f"task_{task_id}"
        metadata = {
            "type": "events",
            "date": date,
            "task_id": task_id,
            "ts_start": first_ts,
            "ts_end": last_ts,
            "event_count": len(events),
        }

        if upsert_history_chunk(doc_id, text, metadata, client=client):
            count += 1

    # Index standalone events in small batches (group by date)
    by_date = {}
    for ev in standalone_events:
        date = ev.get("ts", "")[:10]
        by_date.setdefault(date, []).append(ev)

    for date, evts in by_date.items():
        lines = []
        for ev in evts:
            ev_type = ev.get("type", "?")
            ts = ev.get("ts", "")[:16]
            preview = ev.get("thought_preview", ev.get("summary", ""))
            line = f"[{ts}] {ev_type}"
            if preview:
                line += f": {preview[:200]}"
            lines.append(line)

        text = "\n".join(lines)
        if len(text) > 2000:
            text = text[:2000] + "..."

        doc_id = f"events_standalone_{date}"
        metadata = {
            "type": "events",
            "date": date,
            "event_count": len(evts),
        }

        if upsert_history_chunk(doc_id, text, metadata, client=client):
            count += 1

    return count


def print_summary(client):
    """Print collection counts."""
    print("\n=== Collection Summary ===")
    for name in ("thai_episodes", "thai_skills", "thai_history"):
        try:
            col = client.get_or_create_collection(name=name)
            print(f"  {name}: {col.count()} entries")
        except Exception as e:
            print(f"  {name}: ERROR - {e}")


def main():
    print("Connecting to ChromaDB...")
    client = get_client()
    print("Connected.\n")

    print("1. Indexing episodic memory...")
    ep_count, skill_count = index_episodic(client)
    print(f"   -> {ep_count} episodes, {skill_count} skills\n")

    print("2. Indexing chat history...")
    chat_count = index_chat(client)
    print(f"   -> {chat_count} chat sessions\n")

    print("3. Indexing events...")
    event_count = index_events(client)
    print(f"   -> {event_count} event groups\n")

    print_summary(client)
    print("\nDone!")


if __name__ == "__main__":
    main()
