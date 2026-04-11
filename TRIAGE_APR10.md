# Triage: THAI operations Apr 6-10, 2026

## P1: THAI halted since 2026-04-09 12:02 UTC

**Root cause:** Manual `/panic` from Shareholder at 12:02:56 UTC.

**Context:** Budget $417/$400 (exceeded), two consecutive tasks hit MAX_ROUNDS=12
with "Announcement without execution" pattern (Inner Critic flagged both).
Shareholder sent `/panic` 24 seconds after last idle heartbeat.

**Fix:** None needed — intentional shutdown.

## P2: 18 `llm_empty_response` events (6-10 Apr)

**Root cause:** All 18 were on round 13 (MAX_ROUNDS+1), attempt 1-3 —
standard circuit breaker termination, not LLM failures.

**Fix:** Relabeled as `circuit_breaker_empty` in loop.py (1 line).
Event type now correctly distinguishes circuit breaker from real empty responses.

## P3: overplanning — resolved via kill switch

### Implemented (this branch)
- **Kill switch:** `STRATEGIC_PLANNER_ENABLED` env var, default `"false"`.
  Planner disabled until context issues resolved. Logs `strategic_planner_disabled`.
- **D: budget guard** at 95% (`STRATEGIC_PLAN_BUDGET_THRESHOLD = 0.95`) —
  safety valve for when planner is re-enabled. Logs `strategic_plan_blocked_budget`.

### Abandoned (fix/post-apr10-triage branch)
- B: plan-commitment tracker — would block ALL plans permanently because
  dispatcher never delivers planned tasks (see P4).
- C: daily plan cap — redundant while kill switch is active.

Branch `fix/post-apr10-triage` can be deleted after this merge.

## P4: dispatcher does not handle `planned_task` — closed, no fix

**Diagnosed.** `planned_task` and `proactive_message` event types were never
added to `supervisor/events.py` EVENT_HANDLERS (git history confirms: never
existed, original oversight in commit `1c11209`).

**Impact (Apr 6-10):**
- 112 `planned_task` events dropped (all fell to `unknown_worker_event`)
- 141 `proactive_message` events dropped (133 gate notifications, 8 plan summaries)
- Shareholder never saw gate approval requests → could not `/approve`

**Decision: no dispatcher fix.** Diagnosis of the 112 planned tasks revealed
the strategic planner generates hallucinated tasks:
- 6/15 sampled tasks reference archived "AI Company" / CrewAI multi-agent system
- 7/15 are thematic duplicates ("await Prism V2 input" × 7 variations)
- 0/15 would have been genuinely useful
- Estimated waste if dispatcher worked: ~$112 on garbage tasks

Fixing the dispatcher would only deliver hallucinated tasks to the queue.
The real fix is planner context (P5), not delivery infrastructure.

## P5: Strategic planner context outdated (NEW — out of scope)

The strategic planner (`ouroboros/strategic_planner.py`) generates plans
based on stale context that includes references to:
- "AI Company" multi-agent architecture (archived Feb 2026)
- CrewAI crew structure (replaced by Ouroboros)
- "Agent performance metrics" for non-existent agents

**Before re-enabling** (`STRATEGIC_PLANNER_ENABLED=true`):
1. Audit planner's context assembly — what does it read?
2. Strip references to archived systems
3. Add current product state (Prism V2 status, VendorLens paused)
4. Test with 5 plan generations, verify 0 hallucinated tasks
5. Only then: enable planner + add `planned_task` handler to dispatcher

Scheduled separately from this triage.
