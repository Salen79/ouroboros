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

## P3: overplanning — partial fix only

### Implemented (this branch)
- D: budget guard at 95% (`STRATEGIC_PLAN_BUDGET_THRESHOLD = 0.95`) —
  safety valve, valid regardless of dispatcher state.
  Logs `strategic_plan_blocked_budget` event with spent/threshold values.

### Frozen in fix/post-apr10-triage (NOT merged)
- B: plan-commitment tracker (in-memory, checks task_received for >50% keyword match)
- C: daily plan cap via `OUROBOROS_MAX_PLANS_PER_DAY` env (default 4)

### Why frozen
Side discovery during P3 implementation: `planned_task` events from
consciousness.py are NOT handled by supervisor/events.py dispatcher —
they fall into `unknown_worker_event`. Non-gated tasks from strategic
plans never reach the queue. This means:
- The "31% plan→execution conversion" was actually gated approval rate
- The 51% duplicate rate is a symptom: planner has no execution feedback
- B (plan-commitment tracker) would block ALL plans permanently after
  the first one, because no plan tasks ever complete

B and C are valid fixes IF the dispatcher bug is fixed first. Until then,
merging them would mask the real problem and freeze the strategic planner.

### Next: fix/dispatcher-planned-task
See P4 below.

## P4: dispatcher does not handle `planned_task` (NEW)

Status: discovered during P3, not yet diagnosed.
Branch: fix/dispatcher-planned-task (to be created after P3 merge).
Approach: diagnostic-first, same protocol as P1-P3.
