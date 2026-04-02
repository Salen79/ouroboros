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


class StuckDetector:
    """Detect when consciousness keeps producing the same thought."""

    def __init__(self, threshold: int = 3):
        self.recent_thoughts: List[str] = []
        self.threshold = threshold
        self._alerted = False

    def check(self, thought: str) -> bool:
        """Returns True if stuck (N consecutive similar thoughts)."""
        self.recent_thoughts.append(thought[:200].lower())
        if len(self.recent_thoughts) > self.threshold + 1:
            self.recent_thoughts.pop(0)

        if len(self.recent_thoughts) < self.threshold:
            return False

        # Check similarity: shared words / average total words
        word_sets = [set(t.split()) for t in self.recent_thoughts[-self.threshold:]]
        if not word_sets or any(len(w) == 0 for w in word_sets):
            return False

        common = word_sets[0]
        for ws in word_sets[1:]:
            common = common & ws

        avg_len = sum(len(w) for w in word_sets) / len(word_sets)
        similarity = len(common) / max(avg_len, 1)

        return similarity > 0.7

    def reset(self):
        self.recent_thoughts.clear()
        self._alerted = False


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

        # Strategic planning state
        self._last_plan_ts: float = 0.0
        self._plan_interval_sec: float = 1800.0  # 30 min between plan attempts
        self._pending_gated_tasks: list = []  # Tasks waiting for /approve

        # Budget tracking
        self._bg_spent_usd: float = 0.0
        self._bg_budget_pct: float = float(
            os.environ.get("OUROBOROS_BG_BUDGET_PCT", "10")
        )

        # Daily chat backup
        self._backup_ts_path = self._drive_root / "state" / "last_chat_backup.txt"
        self._BACKUP_INTERVAL_SEC = 23 * 3600

        # Stuck detector — alerts after 3 consecutive similar thoughts
        self._stuck_detector = StuckDetector(threshold=3)

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

            # Strategic planning when queue is empty
            self._maybe_strategic_plan()

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

    def _maybe_strategic_plan(self) -> None:
        """Run strategic planner when task queue is empty. No LLM budget — planner handles that."""
        now = time.time()
        if now - self._last_plan_ts < self._plan_interval_sec:
            return

        # Only plan when queue is empty and no tasks running
        try:
            from supervisor.workers import RUNNING, PENDING
            if RUNNING or PENDING:
                return
        except Exception:
            return

        self._last_plan_ts = now
        log.info("Consciousness: task queue empty — running strategic planner")

        try:
            from ouroboros.strategic_planner import StrategicPlanner
            planner = StrategicPlanner(repo_dir=self._repo_dir, drive_root=self._drive_root)
            plan = planner.generate_plan()

            if not plan.tasks:
                return

            # Send plan summary to shareholder via Telegram
            summary = planner.format_telegram_summary(plan)
            chat_id = self._owner_chat_id_fn()
            if chat_id and self._event_queue is not None:
                self._event_queue.put({
                    "type": "proactive_message",
                    "text": summary,
                    "chat_id": chat_id,
                    "ts": utc_now_iso(),
                })

            # Queue non-gated tasks, hold gated ones for /approve
            for task in plan.tasks:
                if task.requires_gate:
                    self._pending_gated_tasks.append(task)
                    # Notify shareholder about gate
                    if chat_id and self._event_queue is not None:
                        self._event_queue.put({
                            "type": "proactive_message",
                            "text": (
                                f"🔒 Gate required: {task.title}\n"
                                f"Reason: {task.gate_reason}\n"
                                f"Send /approve or /reject"
                            ),
                            "chat_id": chat_id,
                            "ts": utc_now_iso(),
                        })
                else:
                    # Queue as a task
                    if self._event_queue is not None:
                        self._event_queue.put({
                            "type": "planned_task",
                            "description": f"[Plan] {task.title}: {task.description}",
                            "category": task.category,
                            "est_cost": task.est_cost,
                            "ts": utc_now_iso(),
                        })

            # Post-plan health check
            try:
                from ouroboros.self_evolution import SelfEvolution
                evo = SelfEvolution(repo_dir=self._repo_dir)
                health = evo.health_check()
                if health.get("status") != "ok":
                    log.warning("Post-plan health check: %s", health.get("status"))
                    if chat_id and self._event_queue is not None:
                        self._event_queue.put({
                            "type": "proactive_message",
                            "text": f"⚠️ Health check after planning: {health.get('status')}\n{json.dumps(health, indent=2)[:500]}",
                            "chat_id": chat_id,
                            "ts": utc_now_iso(),
                        })
            except Exception as e:
                log.debug("Post-plan health check failed: %s", e)

            # Log the plan
            append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                "ts": utc_now_iso(),
                "type": "strategic_plan_generated",
                "task_count": len(plan.tasks),
                "gated_count": sum(1 for t in plan.tasks if t.requires_gate),
                "total_est_cost": sum(t.est_cost for t in plan.tasks),
            })

        except ImportError:
            log.debug("Strategic planner not available yet")
        except Exception as e:
            log.error("Strategic planning failed: %s", e)
            append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                "ts": utc_now_iso(),
                "type": "strategic_plan_error",
                "error": repr(e),
            })

    def approve_gated_task(self, index: int = 0) -> str:
        """Approve a pending gated task. Called from /approve command."""
        if not self._pending_gated_tasks:
            return "No pending gated tasks."
        if index >= len(self._pending_gated_tasks):
            return f"Invalid index {index}. {len(self._pending_gated_tasks)} pending."

        task = self._pending_gated_tasks.pop(index)
        task.approved = True

        # Queue the approved task
        if self._event_queue is not None:
            self._event_queue.put({
                "type": "planned_task",
                "description": f"[Approved] {task.title}: {task.description}",
                "category": task.category,
                "est_cost": task.est_cost,
                "ts": utc_now_iso(),
            })

        return f"✅ Approved: {task.title}"

    def reject_gated_task(self, index: int = 0, reason: str = "") -> str:
        """Reject a pending gated task. Called from /reject command."""
        if not self._pending_gated_tasks:
            return "No pending gated tasks."
        if index >= len(self._pending_gated_tasks):
            return f"Invalid index {index}. {len(self._pending_gated_tasks)} pending."

        task = self._pending_gated_tasks.pop(index)
        reason_text = f" — {reason}" if reason else ""
        return f"❌ Rejected: {task.title}{reason_text}"

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

    def _maybe_consolidate_scratchpad(self) -> float:
        """Consolidate scratchpad if it exceeds ~2000 tokens (~8000 chars).

        Uses light model to extract durable facts, saves them via record_memory,
        then compresses scratchpad to essentials. Returns cost spent.
        """
        scratchpad_path = self._drive_root / "memory" / "scratchpad.md"
        if not scratchpad_path.exists():
            return 0.0

        content = read_text(scratchpad_path)
        if len(content) < 8000:
            return 0.0

        log.info("Scratchpad consolidation triggered: %d chars", len(content))

        prompt = (
            "You are a memory consolidation engine for an autonomous AI agent.\n"
            "The agent's scratchpad has grown too large. Extract the durable facts "
            "(decisions, insights, important state) and return them as JSON.\n\n"
            "SCRATCHPAD CONTENT:\n" + content[:12000] + "\n\n"
            "Return JSON:\n"
            '{"durable_facts": [{"title": "...", "content": "...", "tags": ["..."]}], '
            '"compressed_scratchpad": "# Scratchpad\\n\\n(compressed essentials here)"}\n\n'
            "Rules:\n"
            "- durable_facts: 3-8 most important facts worth remembering long-term\n"
            "- compressed_scratchpad: keep ONLY active tasks, current focus, and recent decisions (under 3000 chars)\n"
            "- Preserve any TODO items or action items in the compressed scratchpad"
        )

        try:
            model = self._model
            msg, usage = self._llm.chat(
                messages=[
                    {"role": "system", "content": "You are a concise memory consolidation engine."},
                    {"role": "user", "content": prompt},
                ],
                model=model,
                reasoning_effort="low",
                max_tokens=2048,
            )
            cost = float(usage.get("cost") or 0)

            response_text = msg.get("content", "")
            parsed = self._parse_reflection_json(response_text)
            if not parsed:
                log.warning("Scratchpad consolidation: failed to parse LLM response")
                return cost

            # Save durable facts as episodic memories
            durable_facts = parsed.get("durable_facts", [])
            for fact in durable_facts[:8]:
                title = fact.get("title", "Scratchpad fact")
                fact_content = fact.get("content", "")
                tags = fact.get("tags", [])
                if not fact_content:
                    continue

                entry = {
                    "ts": utc_now_iso(),
                    "type": "insight",
                    "title": title[:200],
                    "content": fact_content[:2000],
                    "tags": (tags + ["scratchpad_consolidation"])[:10],
                    "importance": 3,
                }

                # Write to episodic memory
                ep_dir = self._drive_root / "memory" / "episodic"
                ep_dir.mkdir(parents=True, exist_ok=True)
                today = entry["ts"][:10]
                ep_file = ep_dir / f"{today}.jsonl"
                with ep_file.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")

                # Sync to ChromaDB
                try:
                    from ouroboros.tools.semantic_memory import upsert_episode
                    upsert_episode(entry)
                except Exception:
                    pass

            # Write compressed scratchpad
            compressed = parsed.get("compressed_scratchpad", "")
            if compressed and len(compressed) < len(content):
                from ouroboros.utils import write_text
                write_text(scratchpad_path, compressed)
                log.info("Scratchpad consolidated: %d -> %d chars, %d facts extracted",
                         len(content), len(compressed), len(durable_facts))
            else:
                log.warning("Scratchpad consolidation: compressed version not smaller, skipping write")

            # Log to scratchpad_journal.jsonl
            journal_path = self._drive_root / "memory" / "scratchpad_journal.jsonl"
            append_jsonl(journal_path, {
                "ts": utc_now_iso(),
                "type": "consolidation",
                "original_chars": len(content),
                "compressed_chars": len(compressed) if compressed else 0,
                "facts_extracted": len(durable_facts),
                "cost_usd": cost,
            })

            return cost

        except Exception as e:
            log.warning("Scratchpad consolidation failed: %s", e)
            return 0.0

    def _think(self) -> None:
        """One thinking cycle: build context, call LLM, execute tools iteratively."""
        # Auto-consolidate scratchpad if too large
        try:
            consolidation_cost = self._maybe_consolidate_scratchpad()
            self._bg_spent_usd += consolidation_cost
        except Exception as e:
            log.debug("Scratchpad consolidation error: %s", e)

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
            thought_preview = (final_content or "")[:300]
            append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                "ts": utc_now_iso(),
                "type": "consciousness_thought",
                "thought_preview": thought_preview,
                "cost_usd": total_cost,
                "rounds": round_idx,
                "model": model,
            })

            # Stuck detection — alert + extend sleep if repeating same thought
            if thought_preview and self._stuck_detector.check(thought_preview):
                if not self._stuck_detector._alerted:
                    try:
                        if self._event_queue is not None and self._owner_chat_id_fn():
                            self._event_queue.put({
                                "type": "proactive_message",
                                "text": (
                                    "⚠️ Consciousness stuck: repeating same thought "
                                    f"{self._stuck_detector.threshold}x in a row. "
                                    "Extending sleep to 2 hours. Will resume normally after."
                                ),
                                "chat_id": self._owner_chat_id_fn(),
                                "ts": utc_now_iso(),
                            })
                    except Exception:
                        pass
                    self._stuck_detector._alerted = True
                self._next_wakeup_sec = 7200  # 2 hours
                log.warning("Stuck detector triggered — extending sleep to 2h")
                append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                    "ts": utc_now_iso(),
                    "type": "consciousness_stuck",
                    "thought_preview": thought_preview,
                    "extended_sleep_sec": 7200,
                })
            else:
                self._stuck_detector._alerted = False

            # Commitment accountability check
            try:
                from supervisor.queue import CommitmentTracker
                _tracker = CommitmentTracker(self._drive_root / "state")
                _expired = _tracker.get_expired()
                for _c in _expired:
                    _desc = _c["description"][:80]
                    _overdue = _c.get("minutes_overdue", 0)
                    if self._event_queue is not None and self._owner_chat_id_fn():
                        self._event_queue.put({
                            "type": "proactive_message",
                            "text": (
                                f"⏰ Commitment overdue: \"{_desc}\" — "
                                f"{_overdue}min past deadline. Starting now or dropping?"
                            ),
                            "chat_id": self._owner_chat_id_fn(),
                            "ts": utc_now_iso(),
                        })
            except Exception as _ce:
                log.debug("Commitment check failed: %s", _ce)

            # Auto-reflection on completed tasks (budget-aware)
            try:
                reflection_cost = self._auto_reflect()
                total_cost += reflection_cost
                self._bg_spent_usd += reflection_cost
            except Exception as e:
                log.debug("Auto-reflection failed: %s", e)

        except Exception as e:
            append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                "ts": utc_now_iso(),
                "type": "consciousness_llm_error",
                "error": repr(e),
            })

    # -------------------------------------------------------------------
    # Auto-reflection on completed tasks
    # -------------------------------------------------------------------

    def _auto_reflect(self) -> float:
        """Reflect on recently completed tasks. Returns total cost spent."""
        cost_spent = 0.0

        # Find new task_done events not yet reflected
        events_path = self._drive_root / "logs" / "events.jsonl"
        reflected_path = self._drive_root / "state" / "reflected_tasks.json"

        if not events_path.exists():
            return 0.0

        # Load already-reflected task IDs
        reflected_ids = set()
        if reflected_path.exists():
            try:
                reflected_ids = set(json.loads(read_text(reflected_path)))
            except Exception:
                reflected_ids = set()

        # Find task_done events with cost >= $0.01 (skip trivial tasks)
        candidates = []
        lines = read_text(events_path).strip().split("\n")
        for line in lines[-200:]:  # Only look at recent events
            try:
                ev = json.loads(line)
                if ev.get("type") != "task_done":
                    continue
                task_id = ev.get("task_id")
                cost = float(ev.get("cost_usd", 0))
                if not task_id or task_id in reflected_ids or cost < 0.01:
                    continue
                candidates.append(ev)
            except (json.JSONDecodeError, ValueError):
                continue

        if not candidates:
            return 0.0

        # Cap: max 3 reflections per cycle
        candidates = candidates[-3:]

        for ev in candidates:
            task_id = ev.get("task_id", "")

            # Check per-cycle cost cap
            try:
                consciousness_cost_cap = float(
                    os.environ.get("OUROBOROS_CONSCIOUSNESS_COST_CAP", "0.10")
                )
            except (ValueError, TypeError):
                consciousness_cost_cap = 0.10
            if cost_spent > consciousness_cost_cap * 0.5:
                break  # Reserve half the cap for regular thinking

            # Load task result
            result_path = self._drive_root / "task_results" / f"{task_id}.json"
            if not result_path.exists():
                reflected_ids.add(task_id)
                continue

            try:
                task_data = json.loads(read_text(result_path))
            except Exception:
                reflected_ids.add(task_id)
                continue

            task_result = task_data.get("result", "")[:1500]
            task_cost = task_data.get("cost_usd", 0)
            task_rounds = task_data.get("total_rounds", 0)

            # Generate reflection via light model
            reflection_prompt = (
                f"You are THAI, an autonomous AI CEO. A task just completed.\n"
                f"Task ID: {task_id}\n"
                f"Cost: ${task_cost:.4f}, Rounds: {task_rounds}\n"
                f"Result:\n{task_result}\n\n"
                f"Write a brief reflection (2-4 sentences):\n"
                f"1. What was learned?\n"
                f"2. Any error patterns to avoid next time?\n"
                f"3. If this was a procedural task, describe the steps as a reusable skill.\n\n"
                f"Respond in JSON: {{\"type\": \"insight\" or \"error_pattern\" or \"skill\", "
                f"\"title\": \"...\", \"content\": \"...\", \"tags\": [...]}}\n"
                f"If nothing worth noting, respond: {{\"type\": \"skip\"}}"
            )

            try:
                msg, usage = self._llm.chat(
                    messages=[
                        {"role": "system", "content": "You are a concise reflection engine."},
                        {"role": "user", "content": reflection_prompt},
                    ],
                    model=self._model,
                    reasoning_effort="low",
                    max_tokens=512,
                )
                call_cost = float(usage.get("cost") or 0)
                cost_spent += call_cost

                content = msg.get("content", "")
                # Parse JSON from response
                reflection = self._parse_reflection_json(content)

                if reflection and reflection.get("type") != "skip":
                    self._save_reflection(reflection, task_id)
            except Exception as e:
                log.debug("Reflection LLM call failed for task %s: %s", task_id, e)

            reflected_ids.add(task_id)

        # Save reflected IDs (keep last 500 to avoid unbounded growth)
        reflected_list = list(reflected_ids)[-500:]
        try:
            reflected_path.parent.mkdir(parents=True, exist_ok=True)
            reflected_path.write_text(json.dumps(reflected_list), encoding="utf-8")
        except Exception as e:
            log.debug("Failed to save reflected_tasks.json: %s", e)

        return cost_spent

    def _parse_reflection_json(self, text: str) -> dict | None:
        """Extract JSON from LLM reflection response."""
        text = text.strip()
        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try extracting from markdown code block
        import re
        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        # Try finding first { ... }
        start = text.find('{')
        end = text.rfind('}')
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        return None

    def _save_reflection(self, reflection: dict, task_id: str) -> None:
        """Save a reflection as episodic memory entry."""
        ref_type = reflection.get("type", "insight")
        title = reflection.get("title", f"Reflection on task {task_id}")
        content = reflection.get("content", "")
        tags = reflection.get("tags", [])

        if not content:
            return

        if ref_type not in ("insight", "error_pattern", "skill"):
            ref_type = "insight"

        # Add task_id to tags
        if task_id not in tags:
            tags.append(task_id)
        tags.append("auto_reflection")

        from ouroboros.utils import utc_now_iso as _utc_now
        entry = {
            "ts": _utc_now(),
            "type": ref_type,
            "title": title[:200],
            "content": content[:2000],
            "tags": tags[:10],
            "importance": 3,
        }

        # Write to today's episodic file
        ep_dir = self._drive_root / "memory" / "episodic"
        ep_dir.mkdir(parents=True, exist_ok=True)
        today = entry["ts"][:10]
        ep_file = ep_dir / f"{today}.jsonl"
        with ep_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Sync to ChromaDB
        try:
            from ouroboros.tools.semantic_memory import upsert_episode
            upsert_episode(entry)
        except Exception:
            pass

        # If skill type, also save as a proper skill entry
        if ref_type == "skill":
            entry["importance"] = 4
            entry["tags"] = list(set(entry["tags"] + ["skill"]))

        append_jsonl(self._drive_root / "logs" / "events.jsonl", {
            "ts": entry["ts"],
            "type": "auto_reflection",
            "task_id": task_id,
            "reflection_type": ref_type,
            "title": title[:100],
        })

        log.info("Auto-reflection saved: [%s] %s (task %s)", ref_type, title[:60], task_id)

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
        # Semantic memory (read-only)
        "semantic_search", "recall",
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
