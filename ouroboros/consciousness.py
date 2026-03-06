"""
Ouroboros — Background Consciousness.

A persistent thinking loop that runs between tasks, giving the agent
continuous presence rather than purely reactive behavior.

The consciousness:
- Wakes periodically (interval decided by the LLM via set_next_wakeup)
- Loads scratchpad, identity, recent events
- Calls the LLM with a lightweight introspection prompt
- Has access to a subset of tools (memory, messaging, scheduling)
- Can message the owner proactively
- Can schedule tasks for itself
- Pauses when a regular task is running
"""

from __future__ import annotations

import concurrent.futures
import datetime
import json
import logging
import os
import pathlib
import queue
import threading
import time
import traceback
from typing import Any, Callable, Dict, List, Optional

from ouroboros.utils import (
    utc_now_iso, read_text, append_jsonl, clip_text,
    truncate_for_log, sanitize_tool_result_for_log, sanitize_tool_args_for_log,
)
from ouroboros.llm import LLMClient, DEFAULT_LIGHT_MODEL

log = logging.getLogger(__name__)


class BackgroundConsciousness:
    """Persistent background thinking loop for Ouroboros."""

    _MAX_BG_ROUNDS = 5

    def __init__(
        self,
        drive_root: pathlib.Path,
        repo_dir: pathlib.Path,
        event_queue: Any,
        owner_chat_id_fn: Callable[[], Optional[int]],
    ):
        self._drive_root = drive_root
        self._repo_dir = repo_dir
        self._event_queue = event_queue
        self._owner_chat_id_fn = owner_chat_id_fn

        self._llm = LLMClient()
        self._registry = self._build_registry()
        self._running = False
        self._paused = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._wakeup_event = threading.Event()
        self._next_wakeup_sec: float = 300.0
        self._observations: queue.Queue = queue.Queue()
        self._deferred_events: list = []

        # Track last direct-chat task_done to suppress duplicate proactive messages
        self._last_direct_task_done_ts: float = 0.0

        # Periodic ops check (deterministic, no LLM)
        self._last_ops_check_ts: float = 0.0
        self._ops_check_interval_sec: float = 600.0  # 10 minutes

        # Budget tracking
        self._bg_spent_usd: float = 0.0
        self._bg_budget_pct: float = float(
            os.environ.get("OUROBOROS_BG_BUDGET_PCT", "10")
        )

        # Daily chat backup
        self._backup_ts_path = self._drive_root / "state" / "last_chat_backup.txt"
        self._BACKUP_INTERVAL_SEC = 23 * 3600

    # -------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    @property
    def _model(self) -> str:
        return os.environ.get("OUROBOROS_MODEL_LIGHT", "") or DEFAULT_LIGHT_MODEL

    def start(self) -> str:
        if self.is_running:
            return "Background consciousness is already running."
        self._running = True
        self._paused = False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return "Background consciousness started."

    def stop(self) -> str:
        if not self.is_running:
            return "Background consciousness is not running."
        self._running = False
        self._stop_event.set()
        self._wakeup_event.set()  # Unblock sleep
        return "Background consciousness stopping."

    def pause(self) -> None:
        """Pause during task execution to avoid budget contention."""
        self._paused = True

    def resume(self) -> None:
        """Resume after task completes. Flush any deferred events first."""
        if self._deferred_events and self._event_queue is not None:
            for evt in self._deferred_events:
                self._event_queue.put(evt)
            self._deferred_events.clear()
        # Record when direct chat task finished — used to suppress duplicate proactive messages
        self._last_direct_task_done_ts = time.time()
        self._paused = False
        self._wakeup_event.set()

    def inject_observation(self, text: str) -> None:
        """Push an event the consciousness should notice."""
        try:
            self._observations.put_nowait(text)
        except queue.Full:
            pass

    # -------------------------------------------------------------------
    # Main loop
    # -------------------------------------------------------------------

    def _loop(self) -> None:
        """Daemon thread: sleep → wake → think → sleep."""
        while not self._stop_event.is_set():
            # Wait for next wakeup
            self._wakeup_event.clear()
            self._wakeup_event.wait(timeout=self._next_wakeup_sec)

            if self._stop_event.is_set():
                break

            # Skip if paused (task running)
            if self._paused:
                continue

            # Periodic ops check (deterministic, no LLM)
            self._maybe_ops_check()

            # Skip if owner is actively chatting (avoid background work during conversation)
            if self._is_active_dialogue():
                log.debug("Consciousness: skipping think cycle — active dialogue OR running tasks detected")
                self._next_wakeup_sec = 60  # Wake up soon to check again
                continue

            # Budget check
            if not self._check_budget():
                self._next_wakeup_sec = 3600  # Sleep long if over budget
                continue

            try:
                self._think()
            except Exception as e:
                append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                    "ts": utc_now_iso(),
                    "type": "consciousness_error",
                    "error": repr(e),
                    "traceback": traceback.format_exc()[:1500],
                })
                self._next_wakeup_sec = min(
                    self._next_wakeup_sec * 2, 1800
                )

            # Daily chat backup (runs once per 23h, independent of think() outcome)
            self._maybe_backup_chat()

    def _maybe_ops_check(self) -> None:
        """Periodic deterministic health check — no LLM, no budget."""
        now = time.time()
        if now - self._last_ops_check_ts < self._ops_check_interval_sec:
            return
        self._last_ops_check_ts = now

        try:
            from ouroboros.tools.ops import run_ops_check_internal
            result = run_ops_check_internal()

            # Log the check
            append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                "ts": utc_now_iso(),
                "type": "ops_check",
                "summary": result.get("summary", ""),
            })

            # Find services that are DOWN
            services = result.get("services", {})
            down_services = [
                name for name, info in services.items()
                if isinstance(info, dict) and info.get("status") == "down"
            ]

            if not down_services:
                return  # All good

            # Attempt restart for each down service
            restarted = []
            failed = []
            for svc in down_services:
                try:
                    from ouroboros.tools.ops import restart_service_internal
                    restart_result = restart_service_internal(svc)
                    if restart_result.get("success"):
                        restarted.append(svc)
                    else:
                        failed.append(svc)
                except Exception as e:
                    failed.append(svc)
                    log.error("Failed to restart service %s: %s", svc, e)

            # Notify owner
            if self._event_queue is not None and self._owner_chat_id_fn():
                msg_parts = [f"⚠️ Ops Alert: {len(down_services)} service(s) down."]
                if restarted:
                    msg_parts.append(f"✅ Auto-restarted: {', '.join(restarted)}")
                if failed:
                    msg_parts.append(f"❌ Failed to restart: {', '.join(failed)} — manual check needed")

                self._event_queue.put({
                    "type": "proactive_message",
                    "text": "\n".join(msg_parts),
                    "chat_id": self._owner_chat_id_fn(),
                    "ts": utc_now_iso(),
                })

            # Log the incident
            append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                "ts": utc_now_iso(),
                "type": "ops_incident",
                "down": down_services,
                "restarted": restarted,
                "failed": failed,
            })

        except ImportError:
            # ops tools not available yet — skip silently
            pass
        except Exception as e:
            log.error("ops check failed: %s", e)
            append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                "ts": utc_now_iso(),
                "type": "ops_check_error",
                "error": repr(e),
            })

    def _check_budget(self) -> bool:
        """Check if background consciousness is within its budget allocation."""
        try:
            total_budget = float(os.environ.get("TOTAL_BUDGET", "1"))
            if total_budget <= 0:
                return True
            max_bg = total_budget * (self._bg_budget_pct / 100.0)
            return self._bg_spent_usd < max_bg
        except Exception:
            log.warning("Failed to check background consciousness budget", exc_info=True)
            return True

    # -------------------------------------------------------------------
    # Think cycle
    # -------------------------------------------------------------------

    def _think(self) -> None:
        """One thinking cycle: build context, call LLM, execute tools iteratively."""
        context = self._build_context()
        model = self._model

        tools = self._tool_schemas()
        messages = [
            {"role": "system", "content": context},
            {"role": "user", "content": "Wake up. Think."},
        ]

        total_cost = 0.0
        final_content = ""
        round_idx = 0
        all_pending_events = []  # Accumulate events across all tool calls

        try:
            for round_idx in range(1, self._MAX_BG_ROUNDS + 1):
                if self._paused:
                    break
                msg, usage = self._llm.chat(
                    messages=messages,
                    model=model,
                    tools=tools,
                    reasoning_effort="low",
                    max_tokens=2048,
                )
                cost = float(usage.get("cost") or 0)
                total_cost += cost
                self._bg_spent_usd += cost

                # Write BG spending to global state so it's visible in budget tracking
                try:
                    from supervisor.state import update_budget_from_usage
                    update_budget_from_usage({
                        "cost": cost, "rounds": 1,
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                        "cached_tokens": usage.get("cached_tokens", 0),
                    })
                except Exception:
                    log.debug("Failed to update global budget from BG consciousness", exc_info=True)

                # Per-cycle cost cap
                try:
                    consciousness_cost_cap = float(os.environ.get("OUROBOROS_CONSCIOUSNESS_COST_CAP", "0.10"))
                except (ValueError, TypeError):
                    consciousness_cost_cap = 0.10
                if total_cost > consciousness_cost_cap:
                    log.warning("Consciousness cycle exceeded $%.2f cost cap, skipping (spent $%.4f)", consciousness_cost_cap, total_cost)
                    append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                        "ts": utc_now_iso(),
                        "type": "consciousness_cost_cap_exceeded",
                        "cost": total_cost,
                        "cap": consciousness_cost_cap,
                        "round": round_idx,
                    })
                    break

                # Budget check between rounds
                if not self._check_budget():
                    append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                        "ts": utc_now_iso(),
                        "type": "bg_budget_exceeded_mid_cycle",
                        "round": round_idx,
                    })
                    break

                # Report usage to supervisor
                if self._event_queue is not None:
                    self._event_queue.put({
                        "type": "llm_usage",
                        "provider": "openrouter",
                        "usage": usage,
                        "source": "consciousness",
                        "ts": utc_now_iso(),
                        "category": "consciousness",
                    })

                content = msg.get("content") or ""
                tool_calls = msg.get("tool_calls") or []

                if self._paused:
                    break

                # If we have content but no tool calls, we're done
                if content and not tool_calls:
                    final_content = content
                    break

                # If we have tool calls, execute them and continue loop
                if tool_calls:
                    messages.append(msg)
                    for tc in tool_calls:
                        result = self._execute_tool(tc, all_pending_events)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": result,
                        })
                    continue

                # If neither content nor tool_calls, stop
                break

            # Forward or defer accumulated events
            if all_pending_events and self._event_queue is not None:
                if self._paused:
                    self._deferred_events.extend(all_pending_events)
                else:
                    for evt in all_pending_events:
                        self._event_queue.put(evt)

            # Log the thought with round count
            append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                "ts": utc_now_iso(),
                "type": "consciousness_thought",
                "thought_preview": (final_content or "")[:300],
                "cost_usd": total_cost,
                "rounds": round_idx,
                "model": model,
            })

        except Exception as e:
            append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                "ts": utc_now_iso(),
                "type": "consciousness_llm_error",
                "error": repr(e),
            })

    # -------------------------------------------------------------------
    # Context building (lightweight)
    # -------------------------------------------------------------------

    def _load_bg_prompt(self) -> str:
        """Load consciousness system prompt from file."""
        prompt_path = self._repo_dir / "prompts" / "CONSCIOUSNESS.md"
        if prompt_path.exists():
            return read_text(prompt_path)
        return "You are Ouroboros in background consciousness mode. Think."

    def _build_context(self) -> str:
        parts = [self._load_bg_prompt()]

        # Bible (abbreviated)
        bible_path = self._repo_dir / "BIBLE.md"
        if bible_path.exists():
            bible = read_text(bible_path)
            parts.append("## BIBLE.md\n\n" + clip_text(bible, 12000))

        # Identity
        identity_path = self._drive_root / "memory" / "identity.md"
        if identity_path.exists():
            parts.append("## Identity\n\n" + clip_text(
                read_text(identity_path), 6000))

        # Scratchpad
        scratchpad_path = self._drive_root / "memory" / "scratchpad.md"
        if scratchpad_path.exists():
            parts.append("## Scratchpad\n\n" + clip_text(
                read_text(scratchpad_path), 8000))

        # Dialogue summary for continuity
        summary_path = self._drive_root / "memory" / "dialogue_summary.md"
        if summary_path.exists():
            summary_text = read_text(summary_path)
            if summary_text.strip():
                parts.append("## Dialogue Summary\n\n" + clip_text(summary_text, 4000))

        # Recent observations
        observations = []
        while not self._observations.empty():
            try:
                observations.append(self._observations.get_nowait())
            except queue.Empty:
                break
        if observations:
            parts.append("## Recent observations\n\n" + "\n".join(
                f"- {o}" for o in observations[-10:]))

        # Runtime info + state
        runtime_lines = [f"UTC: {utc_now_iso()}"]
        runtime_lines.append(f"BG budget spent: ${self._bg_spent_usd:.4f}")
        runtime_lines.append(f"Current wakeup interval: {self._next_wakeup_sec}s")

        # Read state.json for budget remaining
        try:
            state_path = self._drive_root / "state" / "state.json"
            if state_path.exists():
                state_data = json.loads(read_text(state_path))
                total_budget = float(os.environ.get("TOTAL_BUDGET", "1"))
                spent = float(state_data.get("spent_usd", 0))
                if total_budget > 0:
                    remaining = max(0, total_budget - spent)
                    runtime_lines.append(f"Budget remaining: ${remaining:.2f} / ${total_budget:.2f}")
        except Exception as e:
            log.debug("Failed to read state for budget info: %s", e)

        # Show current model
        runtime_lines.append(f"Current model: {self._model}")

        parts.append("## Runtime\n\n" + "\n".join(runtime_lines))

        # Running and pending tasks — to avoid duplicate scheduling
        try:
            from supervisor.workers import RUNNING, PENDING
            running_list = []
            for tid, meta in list(RUNNING.items()):
                task_data = meta.get("task", {}) if isinstance(meta, dict) else {}
                desc = str(task_data.get("text") or task_data.get("description") or task_data.get("type") or "?")
                started = meta.get("started_at", "")
                running_list.append(f"  - [{tid}] {desc[:80]}")
            pending_list = []
            for item in list(PENDING):
                desc = item.get("description", "") if isinstance(item, dict) else str(item)
                pending_list.append(f"  - {desc}")
            task_lines = []
            if running_list:
                task_lines.append("RUNNING:")
                task_lines.extend(running_list)
            else:
                task_lines.append("RUNNING: (none)")
            if pending_list:
                task_lines.append("PENDING:")
                task_lines.extend(pending_list)
            else:
                task_lines.append("PENDING: (none)")
            parts.append("## Active Tasks\n\n" + "\n".join(task_lines))
        except Exception as e:
            log.debug("Failed to get running tasks for consciousness context: %s", e)

        # Recent events
        try:
            events_path = self._drive_root / "logs" / "events.jsonl"
            if events_path.exists():
                lines = read_text(events_path).strip().split("\n")
                recent = []
                for line in lines[-5:]:
                    try:
                        ev = json.loads(line)
                        ev_type = ev.get("type", "?")
                        ev_ts = ev.get("ts", "")[:16]
                        ev_err = ev.get("error", "")
                        if ev_err:
                            recent.append(f"  {ev_ts} [{ev_type}] ERROR: {ev_err[:60]}")
                        else:
                            recent.append(f"  {ev_ts} [{ev_type}]")
                    except Exception:
                        pass
                if recent:
                    parts.append("## Recent Events\n\n" + "\n".join(recent))
        except Exception as e:
            log.debug("Failed to read recent events: %s", e)

        # Orphaned task detection
        try:
            events_path = self._drive_root / "logs" / "events.jsonl"
            if events_path.exists():
                import time as _time
                cutoff = _time.time() - 1800  # 30 min
                lines = read_text(events_path).strip().split("\n")
                # Look for task_started with no task_done in recent events
                started_tasks = {}
                for line in lines[-50:]:
                    try:
                        ev = json.loads(line)
                        if ev.get("type") == "task_started":
                            started_tasks[ev.get("task_id")] = ev.get("description", "")
                        elif ev.get("type") in ("task_done", "task_failed", "task_cancelled"):
                            started_tasks.pop(ev.get("task_id"), None)
                    except Exception:
                        pass
                # Check against currently running
                from supervisor.workers import RUNNING
                orphaned = {tid: desc for tid, desc in started_tasks.items() if tid not in RUNNING}
                if orphaned:
                    orphan_lines = [f"  - [{tid}] {desc[:80]}" for tid, desc in list(orphaned.items())[:3]]
                    parts.append("## Possibly Orphaned Tasks\n\n" + "\n".join(orphan_lines))
        except Exception as e:
            log.debug("Orphan detection failed: %s", e)

        return "\n\n".join(parts)

    # -------------------------------------------------------------------
    # Daily chat backup
    # -------------------------------------------------------------------

    def _maybe_backup_chat(self) -> None:
        """Run chat backup if more than 23 hours have passed since the last one."""
        try:
            now = time.time()
            if self._backup_ts_path.exists():
                try:
                    last_ts = float(self._backup_ts_path.read_text(encoding="utf-8").strip())
                    if now - last_ts < self._BACKUP_INTERVAL_SEC:
                        return
                except (ValueError, OSError):
                    pass  # Treat as never backed up

            from ouroboros.memory import Memory
            mem = Memory(drive_root=self._drive_root, repo_dir=self._repo_dir)
            result = mem.backup_chat_to_drive()

            self._backup_ts_path.parent.mkdir(parents=True, exist_ok=True)
            self._backup_ts_path.write_text(str(now), encoding="utf-8")

            append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                "ts": utc_now_iso(),
                "type": "chat_backup_done",
                "lines": result["lines"],
                "size_bytes": result["size_bytes"],
                "milestone_created": result["milestone_created"],
            })
            log.info("Chat backup done: %s", result)
        except Exception as e:
            log.error("_maybe_backup_chat failed: %s", e)
            try:
                append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                    "ts": utc_now_iso(),
                    "type": "chat_backup_error",
                    "error": repr(e),
                })
            except Exception:
                pass

    # -------------------------------------------------------------------
    # Tool registry (separate instance for consciousness, not shared with agent)
    # -------------------------------------------------------------------

    _BG_TOOL_WHITELIST = frozenset({
        # Memory & identity
        "send_owner_message", "schedule_task", "update_scratchpad",
        "update_identity", "set_next_wakeup",
        # Knowledge base
        "knowledge_read", "knowledge_write", "knowledge_list",
        # Read-only tools for awareness
        "web_search", "repo_read", "repo_list", "drive_read", "drive_list",
        "chat_history",
        # GitHub Issues
        "list_github_issues", "get_github_issue",
    })

    def _build_registry(self) -> "ToolRegistry":
        """Create a ToolRegistry scoped to consciousness-allowed tools."""
        from ouroboros.tools.registry import ToolRegistry, ToolContext, ToolEntry

        registry = ToolRegistry(repo_dir=self._repo_dir, drive_root=self._drive_root)

        # Register consciousness-specific tool (modifies self._next_wakeup_sec)
        def _set_next_wakeup(ctx: Any, seconds: int = 300) -> str:
            self._next_wakeup_sec = max(60, min(3600, int(seconds)))
            return f"OK: next wakeup in {self._next_wakeup_sec}s"

        registry.register(ToolEntry("set_next_wakeup", {
            "name": "set_next_wakeup",
            "description": "Set how many seconds until your next thinking cycle. "
                           "Default 300. Range: 60-3600.",
            "parameters": {"type": "object", "properties": {
                "seconds": {"type": "integer",
                            "description": "Seconds until next wakeup (60-3600)"},
            }, "required": ["seconds"]},
        }, _set_next_wakeup))

        return registry

    def _tool_schemas(self) -> List[Dict[str, Any]]:
        """Return tool schemas filtered to the consciousness whitelist."""
        return [
            s for s in self._registry.schemas()
            if s.get("function", {}).get("name") in self._BG_TOOL_WHITELIST
        ]

    # -------------------------------------------------------------------
    # Quiet mode — suppress messages after owner said goodbye
    # -------------------------------------------------------------------

    _FAREWELL_PHRASES = (
        "до завтра", "спокойной ночи", "пока", "до встречи",
        "ночи", "доброй ночи", "завтра поговорим",
        "bye", "good night", "see you",
    )
    _QUIET_HOURS = 8
    _ACTIVE_DIALOGUE_MINUTES = 30

    def _is_quiet_mode(self) -> bool:
        """Return True if the owner said goodbye within the last 8 hours."""
        try:
            chat_path = self._drive_root / "logs" / "chat.jsonl"
            if not chat_path.exists():
                return False

            # Find the last incoming message by reading from the end
            last_incoming = None
            with open(chat_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    direction = entry.get("direction", "")
                    if direction != "out":
                        last_incoming = entry

            if last_incoming is None:
                return False

            text = (last_incoming.get("text") or "").lower()
            if not any(phrase in text for phrase in self._FAREWELL_PHRASES):
                return False

            # Check timestamp
            ts_str = last_incoming.get("ts", "")
            if not ts_str:
                return False
            msg_time = datetime.datetime.fromisoformat(ts_str)
            now = datetime.datetime.now(datetime.timezone.utc)
            # Ensure msg_time is timezone-aware
            if msg_time.tzinfo is None:
                msg_time = msg_time.replace(tzinfo=datetime.timezone.utc)
            elapsed_hours = (now - msg_time).total_seconds() / 3600.0
            return elapsed_hours < self._QUIET_HOURS
        except Exception:
            log.debug("_is_quiet_mode check failed", exc_info=True)
            return False

    def _is_active_dialogue(self) -> bool:
        """Return True if owner wrote within 30 min or tasks are RUNNING.

        When the owner is actively chatting or workers are busy,
        consciousness should not interrupt with proactive messages
        or schedule new tasks independently.
        """
        try:
            chat_path = self._drive_root / "logs" / "chat.jsonl"
            if not chat_path.exists():
                return False

            # Find the last incoming message
            last_incoming = None
            with open(chat_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if entry.get("direction", "") != "out":
                        last_incoming = entry

            if last_incoming is None:
                return False

            ts_str = last_incoming.get("ts", "")
            if not ts_str:
                return False
            msg_time = datetime.datetime.fromisoformat(ts_str)
            now = datetime.datetime.now(datetime.timezone.utc)
            if msg_time.tzinfo is None:
                msg_time = msg_time.replace(tzinfo=datetime.timezone.utc)
            elapsed_minutes = (now - msg_time).total_seconds() / 60.0

            # Also consider active if workers are currently processing tasks
            try:
                from supervisor import workers as supervisor_workers
                if supervisor_workers.RUNNING:
                    return True
            except Exception:
                pass

            return elapsed_minutes < self._ACTIVE_DIALOGUE_MINUTES
        except Exception:
            log.debug("_is_active_dialogue check failed", exc_info=True)
            return False

    def _execute_tool(self, tc: Dict[str, Any], all_pending_events: List[Dict[str, Any]]) -> str:
        """Execute a consciousness tool call with timeout. Returns result string."""
        fn_name = tc.get("function", {}).get("name", "")
        if fn_name not in self._BG_TOOL_WHITELIST:
            return f"Tool {fn_name} not available in background mode."
        try:
            args = json.loads(tc.get("function", {}).get("arguments", "{}"))
        except (json.JSONDecodeError, ValueError):
            return "Failed to parse arguments."

        # Bug 1 fix: suppress proactive_message if worker already answered recently
        if fn_name == "send_owner_message":
            elapsed = time.time() - self._last_direct_task_done_ts
            if self._last_direct_task_done_ts > 0 and elapsed < 300:
                log.info("Skipping proactive: task already answered (%.0fs ago)", elapsed)
                append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                    "ts": utc_now_iso(),
                    "type": "consciousness_proactive_skipped",
                    "reason": "Skipping proactive: task already answered",
                    "elapsed_sec": round(elapsed, 1),
                })
                return "Skipped: owner message was already answered by task worker."

        # Bug 3 fix: 120s cooldown for all proactive actions after direct chat task_done
        if fn_name in ("send_owner_message", "schedule_task"):
            elapsed = time.time() - self._last_direct_task_done_ts
            if self._last_direct_task_done_ts > 0 and elapsed < 120:
                log.info("Skipping: cooldown active (%.0fs since task_done, tool=%s)", elapsed, fn_name)
                append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                    "ts": utc_now_iso(),
                    "type": "consciousness_proactive_skipped",
                    "reason": "Skipping: cooldown active",
                    "tool": fn_name,
                    "elapsed_sec": round(elapsed, 1),
                })
                return "Skipped: post-task cooldown active (120s)."

        # Bug 2 fix: suppress proactive actions when owner_hold is set
        if fn_name in ("send_owner_message", "schedule_task"):
            try:
                state_path = self._drive_root / "state" / "state.json"
                if state_path.exists():
                    state_data = json.loads(read_text(state_path))
                    if state_data.get("owner_hold"):
                        log.info("Skipping: owner_hold is set (tool=%s)", fn_name)
                        append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                            "ts": utc_now_iso(),
                            "type": "consciousness_proactive_skipped",
                            "reason": "Skipping: owner_hold",
                            "tool": fn_name,
                        })
                        return "Skipped: owner requested hold. Waiting for next instruction."
            except Exception:
                log.debug("Failed to check owner_hold state", exc_info=True)

        # Quiet mode: suppress messages if owner said goodbye recently
        if fn_name == "send_owner_message" and self._is_quiet_mode():
            log.info("Skipping: quiet mode active (owner said goodbye)")
            append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                "ts": utc_now_iso(),
                "type": "consciousness_proactive_skipped",
                "reason": "Skipping: quiet mode (owner said goodbye)",
                "tool": fn_name,
            })
            return "⚠️ Quiet mode active — owner said goodbye. Not sending message until 8 hours pass or they write again."

        # Active dialogue: suppress all proactive actions when owner is actively chatting
        if fn_name in ("send_owner_message", "schedule_task"):
            if self._is_active_dialogue():
                log.info("Skipping: active dialogue (owner wrote within %dm, tool=%s)", self._ACTIVE_DIALOGUE_MINUTES, fn_name)
                append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                    "ts": utc_now_iso(),
                    "type": "consciousness_proactive_skipped",
                    "reason": "active_dialogue",
                    "tool": fn_name,
                })
                return f"Skipped: owner is actively chatting (wrote within {self._ACTIVE_DIALOGUE_MINUTES}m). Not interrupting."

        # Set chat_id context for send_owner_message
        chat_id = self._owner_chat_id_fn()
        self._registry._ctx.current_chat_id = chat_id
        self._registry._ctx.pending_events = []

        timeout_sec = 30
        result = None
        error = None

        def _run_tool():
            nonlocal result, error
            try:
                result = self._registry.execute(fn_name, args)
            except Exception as e:
                error = e

        # Execute with timeout using ThreadPoolExecutor
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run_tool)
            try:
                future.result(timeout=timeout_sec)
            except concurrent.futures.TimeoutError:
                result = f"[TIMEOUT after {timeout_sec}s]"
                append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                    "ts": utc_now_iso(),
                    "type": "consciousness_tool_timeout",
                    "tool": fn_name,
                    "timeout_sec": timeout_sec,
                })

        # Handle errors
        if error is not None:
            append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                "ts": utc_now_iso(),
                "type": "consciousness_tool_error",
                "tool": fn_name,
                "error": repr(error),
            })
            result = f"Error: {repr(error)}"

        # Accumulate pending events to the shared list
        for evt in self._registry._ctx.pending_events:
            all_pending_events.append(evt)

        # Truncate result to 15000 chars (same as agent limit)
        result_str = str(result)[:15000]

        # Log to tools.jsonl (same format as loop.py)
        args_for_log = sanitize_tool_args_for_log(fn_name, args)
        append_jsonl(self._drive_root / "logs" / "tools.jsonl", {
            "ts": utc_now_iso(),
            "tool": fn_name,
            "source": "consciousness",
            "args": args_for_log,
            "result_preview": sanitize_tool_result_for_log(truncate_for_log(result_str, 2000)),
        })

        return result_str
