"""
Ouroboros — Closed-loop skill lifecycle manager.

Detects → deduplicates → extracts → saves → validates → evolves/retires skills.
All steps code-enforced. No step depends on LLM "wanting" to save.

Called from loop.py after every task completion. Uses cheap LLM (Gemini Flash Lite)
for extraction (~$0.001/call). Stores skills in ChromaDB thai_skills collection
and JSONL episodic files (source of truth).
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from ouroboros.utils import utc_now_iso

log = logging.getLogger(__name__)


class SkillManager:
    """Closed-loop skill lifecycle: auto-extract, dedup, validate, evolve."""

    def __init__(self, chromadb_client, llm_client, episodic_write_fn=None,
                 event_emit_fn=None):
        """
        Args:
            chromadb_client: ChromaDB HttpClient (or None if unavailable).
            llm_client: ouroboros.llm.LLMClient instance.
            episodic_write_fn: Optional callable(entry: dict) to write to JSONL.
                               If None, skills are only stored in ChromaDB.
            event_emit_fn: Optional callable(event: dict) emitting structured
                           events to events.jsonl. Used to surface skill_extracted,
                           skill_dedup_match, skill_retired into the central
                           event stream (D2 closure).
        """
        self._client = chromadb_client
        self._llm = llm_client
        self._episodic_write_fn = episodic_write_fn
        self._event_emit_fn = event_emit_fn
        self._skills_col = None
        if chromadb_client is not None:
            try:
                self._skills_col = chromadb_client.get_or_create_collection("thai_skills")
            except Exception as e:
                log.warning("Failed to get thai_skills collection: %s", e)

    def _emit(self, event: dict) -> None:
        """Best-effort write to events.jsonl via injected callback."""
        if self._event_emit_fn is None:
            return
        try:
            self._event_emit_fn(event)
        except Exception:
            log.debug("event_emit_fn failed", exc_info=True)

    # ------------------------------------------------------------------
    # Step 1: Detection (code-enforced)
    # ------------------------------------------------------------------

    def should_extract(self, task_result: dict) -> bool:
        """Returns True if skill extraction is warranted."""
        rounds = task_result.get("rounds", 0)
        success = task_result.get("success", False)
        task_type = task_result.get("task_type", "")

        if task_type not in ("task", "direct_chat"):
            return False
        if rounds <= 3 or not success:
            return False
        return True

    # ------------------------------------------------------------------
    # Step 2: Deduplication (semantic)
    # ------------------------------------------------------------------

    def find_duplicate(self, summary: str, threshold: float = 0.8) -> Optional[dict]:
        """Semantic search for existing similar skill. Returns match or None."""
        if self._skills_col is None:
            return None

        try:
            count = self._skills_col.count()
            if count == 0:
                return None

            results = self._skills_col.query(
                query_texts=[summary],
                n_results=1,
            )
            if not results["documents"][0]:
                return None

            distance = results["distances"][0][0]
            similarity = 1.0 - distance

            if similarity >= threshold:
                return {
                    "id": results["ids"][0][0],
                    "content": results["documents"][0][0],
                    "metadata": results["metadatas"][0][0],
                    "similarity": similarity,
                }
        except Exception as e:
            log.debug("Dedup query failed: %s", e)

        return None

    # ------------------------------------------------------------------
    # Step 3: Extraction (cheap LLM call)
    # ------------------------------------------------------------------

    def extract_skill(self, task_result: dict) -> Optional[dict]:
        """Distill task steps into a reusable procedure via cheap LLM.

        NOT a question 'should I save?' — a command 'distill the steps'.
        Uses Gemini Flash Lite (~$0.001 per call).
        """
        tool_history = task_result.get("tool_calls", [])
        task_description = task_result.get("task", "")
        result_summary = task_result.get("result", "")

        steps_text = "\n".join(
            f"- {call.get('tool', '?')}: {str(call.get('args', ''))[:200]}"
            for call in tool_history[-15:]
        )

        prompt = (
            "Distill this completed task into a reusable skill procedure.\n\n"
            f"TASK: {task_description[:300]}\n"
            f"RESULT: {result_summary[:200]}\n"
            f"STEPS TAKEN:\n{steps_text}\n\n"
            "Respond in JSON only, no markdown:\n"
            '{"name": "short-kebab-name", '
            '"description": "When to use this skill and what it does (1-2 sentences)", '
            '"steps": ["step 1", "step 2", ...], '
            '"tools_used": ["tool1", "tool2"]}'
        )

        try:
            msg, usage = self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                model="google/gemini-2.5-flash-lite",
                reasoning_effort="low",
                max_tokens=500,
            )

            text = msg.get("content", "")
            text = text.replace("```json", "").replace("```", "").strip()
            return json.loads(text)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            log.debug("Skill extraction parse failed: %s", e)
            return None
        except Exception as e:
            log.warning("Skill extraction LLM call failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # Step 4: Save (ChromaDB + JSONL)
    # ------------------------------------------------------------------

    def _save_skill(self, skill_data: dict, task_result: dict, existing: Optional[dict]) -> Optional[str]:
        """Save or update skill in ChromaDB and JSONL."""
        skill_name = skill_data.get("name", "unnamed-skill")
        description = skill_data.get("description", "")
        steps = skill_data.get("steps", [])
        tools_used = skill_data.get("tools_used", [])

        content = (
            f"SKILL: {skill_name}\n"
            f"{description}\n\n"
            f"STEPS:\n"
            + "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps))
            + f"\n\nTOOLS: {', '.join(tools_used)}"
        )

        metadata = {
            "type": "skill",
            "name": skill_name,
            "tools": ",".join(tools_used[:5]),
            "rounds_at_creation": task_result.get("rounds", 0),
            "avg_rounds": float(task_result.get("rounds", 0)),
            "times_used": 0,
            "times_helped": 0,
            "times_matched": 0,
            "score": 0,
            "created": task_result.get("timestamp", ""),
        }

        # ChromaDB upsert
        if self._skills_col is not None:
            try:
                if existing:
                    self._skills_col.update(
                        ids=[existing["id"]],
                        documents=[content],
                        metadatas=[metadata],
                    )
                else:
                    self._skills_col.add(
                        ids=[str(uuid.uuid4())],
                        documents=[content],
                        metadatas=[metadata],
                    )
            except Exception as e:
                log.warning("ChromaDB skill save failed: %s", e)

        # JSONL write (source of truth)
        if self._episodic_write_fn is not None:
            try:
                entry = {
                    "ts": utc_now_iso(),
                    "type": "skill",
                    "title": f"SKILL: {skill_name}",
                    "content": content,
                    "tags": ["skill", "auto-extracted"] + tools_used[:5],
                    "importance": 4,
                }
                self._episodic_write_fn(entry)
            except Exception as e:
                log.debug("JSONL skill write failed: %s", e)

        # D2: surface skill_extracted into events.jsonl so meta_cognition
        # aggregator (and any other audit) sees the lifecycle event.
        self._emit({
            "ts": utc_now_iso(),
            "type": "skill_extracted",
            "skill_name": skill_name,
            "updated": existing is not None,
            "rounds": task_result.get("rounds", 0),
            "tools": tools_used[:5],
        })

        return skill_name

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def process_completed_task(self, task_result: dict) -> Optional[str]:
        """Called after every task completion.

        Returns skill name if saved/updated, None otherwise.
        """
        # Step 1: Should we extract?
        if not self.should_extract(task_result):
            return None

        # Step 2: Dedup check
        summary = task_result.get("task", "")[:200]
        existing = self.find_duplicate(summary)

        if existing:
            # D2: emit the dedup hit into events.jsonl regardless of branch.
            self._emit({
                "ts": utc_now_iso(),
                "type": "skill_dedup_match",
                "skill_id": existing.get("id", ""),
                "similarity": round(float(existing.get("similarity", 0.0)), 3),
            })
            # Update match count
            try:
                meta = existing["metadata"]
                meta["times_matched"] = int(meta.get("times_matched", 0)) + 1

                if self._skills_col is not None:
                    self._skills_col.update(
                        ids=[existing["id"]],
                        metadatas=[meta],
                    )

                # Only re-extract if this execution was significantly better
                avg_rounds = float(meta.get("avg_rounds", 999))
                current_rounds = task_result.get("rounds", 999)
                if current_rounds >= avg_rounds:
                    return None  # Existing skill is good enough
            except Exception as e:
                log.debug("Dedup update failed: %s", e)

        # Step 3: Extract skill via cheap LLM
        skill_data = self.extract_skill(task_result)
        if not skill_data:
            return None

        # Step 4: Save
        skill_name = self._save_skill(skill_data, task_result, existing)
        if skill_name is None:
            return None

        prefix = "updated" if existing else "new"
        return f"{prefix}:{skill_name}"

    # ------------------------------------------------------------------
    # Post-task validation (called when a task used a found skill)
    # ------------------------------------------------------------------

    def record_skill_usage(self, skill_id: str, rounds_with_skill: int) -> Optional[dict]:
        """Track skill effectiveness after a task that used a found skill.

        Returns usage stats dict, or None if ChromaDB unavailable.
        """
        if self._skills_col is None:
            return None

        try:
            result = self._skills_col.get(ids=[skill_id])
            if not result["metadatas"]:
                return None

            meta = result["metadatas"][0]

            times_used = int(meta.get("times_used", 0)) + 1
            avg_rounds = float(meta.get("avg_rounds", rounds_with_skill))
            creation_rounds = int(meta.get("rounds_at_creation", 10))

            new_avg = (avg_rounds * (times_used - 1) + rounds_with_skill) / times_used

            helped = rounds_with_skill < creation_rounds
            times_helped = int(meta.get("times_helped", 0)) + (1 if helped else 0)
            score = times_helped - (times_used - times_helped)

            meta.update({
                "times_used": times_used,
                "times_helped": times_helped,
                "avg_rounds": round(new_avg, 1),
                "score": score,
            })

            # Auto-retire: score < -3 after 5+ uses
            newly_retired = False
            if score < -3 and times_used >= 5 and not meta.get("retired"):
                meta["retired"] = True
                newly_retired = True

            self._skills_col.update(ids=[skill_id], metadatas=[meta])

            if newly_retired:
                # D2: surface retirement so dashboards can flag attrition.
                self._emit({
                    "ts": utc_now_iso(),
                    "type": "skill_retired",
                    "skill_id": skill_id,
                    "score": score,
                    "times_used": times_used,
                })

            return {
                "helped": helped,
                "score": score,
                "retired": meta.get("retired", False),
            }
        except Exception as e:
            log.debug("record_skill_usage failed: %s", e)
            return None
