# THAI — Autonomous AI CEO (Ouroboros)

## What This Is

THAI (Truly Human AI) is an autonomous AI agent that operates as CEO of a virtual company. It communicates via Telegram, makes operational decisions independently, builds and deploys products, and reports to a single human Shareholder (Sergey). The project is built on the Ouroboros self-evolving agent framework.

**The mission:** Contributing to the growth of human consciousness on Earth — through products that create genuine value. This is a learning platform for AI organization risk management, not just product delivery.

**Constitution:** BIBLE.md v2.1 — based on Bob Chapman's Truly Human Leadership principles. This is THAI's soul and the governance contract between THAI and the Shareholder.

## Current State (April 3, 2026)

**Products:**
- **VendorLens** (vendorlens.app) — AI-powered vendor/pricing page analysis SaaS. Live in production. Strategically paused (doesn't align with P0). FastAPI backend, Next.js frontend, PostgreSQL, Caddy.
- **Prism** (@Prism_analzer_bot) — Active product. Telegram bot for media/content analysis: manipulation detection, omission analysis, credibility checks. V1 tested and working: correctly scores extreme manipulation (0.9) vs neutral text (0.0). Weak spot: "gray zone" texts with subtle framing/cherry-picking — this is V2 territory.

**THAI status:** Running. Budget ~$58 / $400 (85% spent). Total tasks completed: ~460+.

**Active focus:** Prism V2 prompt rewrite (gray zone detection), consciousness growth monitoring.

**Recently completed (April 2-3):**
- Skill Lifecycle System — merged (commit `2f2982b`). Auto-extraction, dedup, validation, auto-retire.
- Experiment Engine — merged. Pattern detection + hypothesis generation + measurement + auto-revert.
- Consciousness Dashboard — deployed at `https://vendorlens.app/consciousness`. Daily metrics across 4 dimensions. 30-day backfill done. Cron at 23:55.
- Task Scope Boundary fix — prevents THAI from scope-creeping after completing primary task.
- Server cleanup — ai-company deleted, archived at `~/archive/ai-company-2026-02.tar.gz`, docker-compose.yml moved to `~/ouroboros/infra/`.
- **3 behavioral fixes merged** (branch `fix/routing-scratchpad`, commit `ca2834f`):
  1. Model routing fix — short Shareholder messages no longer wrongly go to flash-lite
  2. Scratchpad staleness fix — post-task REPLACE instead of append, clears stale /panic banners
  3. Stuck model escalation — after round 5, if 3 rounds with <50 tokens + 0 tools → escalate to full model
- **Prism V1 validation** — tested on 3 texts: manipulation (0.9/0.9/0.0), neutral (0.0/0.7/0.5), conspiracy (0.9/0.9/0.0). Scores are correct for extreme cases.

**Previously completed:**
- Memory System — 3 sessions (semantic search, skills, auto-reflection, context optimization)
- Behavioral Fixes — 3 sessions (amnesia fix, memory hardcode, accountability)
- Self-Evolution System — installed (file zones, smoke tests, strategic planning)

## Architecture

```
Telegram → colab_launcher.py → supervisor/ → agent.py → LLM (OpenRouter)
                                    │
                                    ├── workers.py     (up to 5 parallel)
                                    ├── consciousness.py (background reflection + stuck detector + commitment check + experiment cycle)
                                    ├── queue.py       (task queue + CommitmentTracker)
                                    └── events.py      (event bus → events.jsonl)

ouroboros/
  ├── agent.py          — thin orchestrator + model routing classifier ✅
  ├── consciousness.py  — background cycle: reflection, stuck detection, commitment nudges, experiment engine
  ├── context.py        — prompt assembly + chat history injection + directive injection + restart banner
  ├── loop.py           — tool loop (MAX_ROUNDS=12) + memory protocol + stuck model escalation + skill lifecycle ✅
  ├── llm.py            — OpenRouter client
  ├── memory.py         — scratchpad, identity, chat, directive extraction
  ├── skill_manager.py  — skill lifecycle: auto-extraction (>3 rounds), dedup, Gemini Flash extraction, score validation, auto-retire ✅
  ├── pattern_detector.py — pure Python stats: expensive_repeat, recurring_error, degrading_performance ✅
  ├── experiment_engine.py — hypothesis generation + experiment runner + measurement + auto-revert ✅
  ├── self_evolution.py — file zone enforcement + merge pipeline
  ├── strategic_planner.py — autonomous goal-setting for consciousness.py
  ├── tools/            — auto-discovered plugins (64 total, 39 core)
  │   ├── core.py       — file operations
  │   ├── git.py        — git (self-modification)
  │   ├── shell.py      — shell + Claude Code CLI
  │   ├── search.py     — web search
  │   ├── knowledge.py  — knowledge base (read/write/list) ✅
  │   ├── episodic_memory.py — episodic memory + skills ✅
  │   ├── semantic_memory.py — ChromaDB semantic search + recall ✅
  │   ├── evolution.py  — propose_change, apply_change tools ✅
  │   ├── ops.py        — systemd/infra checks ✅
  │   ├── tool_discovery.py — meta-tool discovery ✅
  │   └── ...
  ├── review.py         — code metrics
  └── budget.py         — daily budget tracking

config/
  └── FILE_ZONES.yaml   — green/yellow/red zone classification for self-modification

scripts/
  ├── smoke_test.py     — 5 pre-merge tests (registry, context, config, imports, memory)
  ├── consciousness_metrics.py — daily aggregator for 4 consciousness dimensions ✅
  ├── memory_stats.py   — ChromaDB + episodic stats
  └── evolution_stats.py — self-modification metrics

company/dashboard/
  └── consciousness-dashboard.html — standalone HTML + Chart.js, served by Caddy ✅
```

## Server

- **VPS:** ISHosting USA (New York), 4 vCPU Xeon / 8 GB RAM / 50 GB SSD, Ubuntu 24.04 — $39.99/mo
- **IP:** 38.180.135.77
- **SSH:** port 2222, user `deploy` (key-only, non-root, sudo)
- **Domain:** vendorlens.app (Cloudflare DNS + CDN + WAF)

### Services

| Service | How | Port | Access |
|---------|-----|------|--------|
| Caddy | systemd | 80, 443 | public |
| VendorLens backend | systemd (uvicorn) | 8100 | localhost |
| VendorLens frontend | systemd (Next.js) | 3000 | localhost |
| Prism backend | systemd | 8001 | localhost |
| Prism frontend | systemd | — | localhost |
| Prism Telegram bot | systemd (prism-bot) | — | Telegram |
| PostgreSQL | Docker | 5432 | localhost |
| Redis | Docker | 6379 | localhost |
| ChromaDB | Docker | 8000 | localhost |
| Consciousness Dashboard | Caddy static | /consciousness | public |

### Service Management
```bash
sudo systemctl status vendorlens-backend vendorlens-frontend caddy prism-backend prism-bot
sudo journalctl -u vendorlens-backend -f
docker compose -f ~/ouroboros/infra/docker-compose.yml ps
```

### SSH Access
```bash
ssh -p 2222 deploy@38.180.135.77
```

## Git

- **Remote:** github.com:Salen79/ouroboros, branch `ouroboros`
- **Product code:** `company/vendor-lens/` (backend + frontend), `company/dashboard/` (consciousness dashboard)
- **Agent code:** `ouroboros/`, `supervisor/`, `prompts/`
- **Archived:** ~/archive/ai-company-2026-02.tar.gz (CrewAI experiment, compressed)
- **Docker infra:** ~/ouroboros/infra/docker-compose.yml (`.env` has `COMPOSE_PROJECT_NAME=ai-company` — critical for Docker to find existing named volumes)

## THAI Configuration

### Environment (~/ouroboros/.env)
```
OPENROUTER_API_KEY=      # Multi-model API
TELEGRAM_BOT_TOKEN=      # THAI Telegram bot
TOTAL_BUDGET=500         # OpenRouter budget cap (USD)
GITHUB_TOKEN=            # GitHub with repo rights
OUROBOROS_MAX_ROUNDS=12  # Hard limit per task (code default also 12)
OUROBOROS_MAX_TASK_COST=5.00   # USD per task cap (code default is $3.00)
OUROBOROS_CONSCIOUSNESS_COST_CAP=0.10  # USD per consciousness cycle
OUROBOROS_DAILY_AUTO_CAP=50.00  # Daily autonomous spending cap
```

### Models (via OpenRouter)
| Role | Model |
|------|-------|
| Primary | anthropic/claude-sonnet-4.6 |
| Code editing | anthropic/claude-sonnet-4.6 |
| Light (consciousness, dedup) | google/gemini-2.5-flash-lite |
| Skill extraction (experiment engine) | google/gemini-2.5-flash-lite (~$0.001/call) |
| Web search | gpt-5 (OpenAI Responses API) |
| Fallback chain | Claude Sonnet → Gemini Pro → GPT-4.1 |

### Model Routing (agent.py `_classify_message_for_routing`)
| Signal | Route | Model |
|--------|-------|-------|
| task_type: evolution, review, consciousness | full | Claude Sonnet 4.6 |
| task_type: task + heavy keywords (implement, fix, deploy, .py...) | full | Claude Sonnet 4.6 |
| Deep dialogue keywords (миссия, план, думаешь, CEO, strategy...) | full | Claude Sonnet 4.6 |
| Any `?` in message | full | Claude Sonnet 4.6 |
| Message >= 20 chars without action keywords | full | Claude Sonnet 4.6 |
| Message < 20 chars, no `?`, no keywords (e.g. "да", "ок") | light | Gemini Flash Lite |
| Stuck escalation: 3 rounds <50 tokens + 0 tools after round 5 | escalate | → Claude Sonnet 4.6 |

### Safety Mechanisms
| Mechanism | Parameter | Action |
|-----------|-----------|--------|
| Per-task cost cap | $5.00 (set via `OUROBOROS_MAX_TASK_COST` in `.env`; code default if unset: $3.00) | Hard stop, decompose |
| Consciousness cost cap | $0.10 | Skip cycle |
| MAX_ROUNDS | 12 (code default; `.env` may override) | Hard stop, decompose |
| Circuit breaker | 3 empty responses | Hard stop |
| Task dedup | >50% keyword overlap | Skip |
| Budget checkpoints | 25/50/75/90% | Report to shareholder |
| Stuck detector | 3 similar thoughts | Alert + extend sleep to 2h |
| **Stuck model escalation** | 3 rounds <50 tokens after R5 | Escalate to full model ✅ |
| Message dedup | >80% similarity in 5min | Skip duplicate outgoing message |
| Directive compliance | Shareholder stop/pause/forget | Inject into all task contexts |
| Commitment tracker | Planned tasks with deadlines | Nudge when overdue |
| Memory protocol (code-enforced) | find_skills + memory_search | Auto-injected before every task |
| Pre-panic snapshot | scratchpad overwrite | Saves state before /panic or /stop |
| **Post-task scratchpad REPLACE** | Every task completion | Clears stale restart banners ✅ |
| Chat history injection | Last 40 messages | Loaded into context after restart |
| Task scope boundary | write_file detection | Nudge to stop after primary task complete |
| Experiment safety | Max 2 concurrent, 1/day, 3-day max, auto-revert | Green zone actions only |

### THAI Commands (Telegram)
| Command | Description |
|---------|-------------|
| `/panic` | Emergency stop (snapshot + kill) |
| `/stop` | Stop workers + consciousness, stay alive |
| `/restart` | Soft restart |
| `/status` | Workers, queue, budget |
| `/plan` | Generate strategic plan |
| `/budget` | Show budget status |
| `/zones` | Show file zone classification |
| `/branches` | Show pending review branches |
| `/evolve` | Trigger self-improvement cycle |
| `/approve` | Approve gated task |
| `/reject` | Reject gated task |
| `/bg start` / `/bg stop` | Background consciousness on/off |
| `/experiments` | Show active + recent experiments |

## Memory System

### Architecture
| Layer | Tool | Storage |
|-------|------|---------|
| Working memory | scratchpad.md | File (REPLACED after every task, not appended) |
| Identity | identity.md | File |
| Strategic knowledge | wisdom.md | File (28KB) |
| Knowledge base | knowledge_read/write | Files in knowledge/ (index only loaded, ~1.5K tokens) |
| Episodic memory | record_memory, memory_search | JSONL files + ChromaDB |
| Skills | save_skill, find_skills | JSONL + ChromaDB (semantic search) + SkillManager lifecycle |
| History RAG | recall | ChromaDB (488+ chat/event chunks) |
| Semantic search | semantic_search, semantic_find_skills | ChromaDB |
| Recent chat | _load_recent_chat(40) | chat.jsonl → context injection |

### Memory Protocol (code-enforced in loop.py)
Before every task: `find_skills()` + `memory_search()` are injected as mandatory first steps.
After tasks >3 rounds: SkillManager auto-extracts skill via Gemini Flash.
After every task: scratchpad.md REPLACED with current state (clears stale restart banners).
Auto-reflection runs in consciousness.py after task completion.

### Skill Lifecycle (skill_manager.py)
- Auto-extraction after tasks with >3 rounds (Gemini Flash, ~$0.001)
- Deduplication: checks ChromaDB for >80% similar skills before saving
- Score validation: skills start at score 0, increment on reuse
- Auto-retire: skills with score < threshold after N uses get deleted
- 26 unit tests

### ChromaDB Collections
| Collection | Entries | Purpose |
|-----------|---------|---------|
| thai_episodes | 137+ | Insights, decisions, errors |
| thai_skills | 25+ | Proven procedures (growing via skill lifecycle) — two writer formats, see ARCHITECTURE_MAP D4 |
| thai_history | 488+ | Chat and event chunks |

## Experiment Engine

Behavioral self-improvement via the scientific method. Runs in consciousness.py background cycle.

### Pipeline
```
Pattern Detector → Hypothesis Generator → Experiment Runner → Measurement Engine
      ↑                                                              |
      └──────────── failed experiments feed new patterns ────────────┘
```

### Components
- **Pattern Detector** (`pattern_detector.py`): Pure Python stats. Scans task_results/, detects expensive_repeat, recurring_error, degrading_performance. No LLM.
- **Hypothesis Generator** (`experiment_engine.py`): Takes pattern + sample histories, generates testable hypothesis via Gemini Flash Lite (~$0.001). Only proposes GREEN zone actions: save_skill, update_skill, add_knowledge.
- **Experiment Runner**: Executes action, records experiment in `state/experiments.json`.
- **Measurement Engine**: After each task in loop.py, checks if task matches active experiment. Concludes when enough data or expired. Auto-reverts on failure (deletes skill/knowledge). Records confirmed experiments in wisdom.md.

### Safety Constraints
- Max 2 concurrent experiments
- Max 1 new experiment per day
- 4h cooldown after conclusion
- 3-day max experiment duration
- Green zone actions only (no code changes — that's self-evolution territory)
- Auto-revert on failed experiments
- Shareholder notification on start/conclude
- 44 unit tests

### State: `~/ouroboros-data/state/experiments.json`

## Consciousness Dashboard

**URL:** `https://vendorlens.app/consciousness`

Daily-updating dashboard tracking THAI's growth across four dimensions:

1. **Meta-Cognition (0-10):** Experiments started/confirmed, self-evolution commits, reflections with action, skill creation, pattern detection, reuse rate. Baseline: 2/10.
2. **Efficiency:** Tasks completed, avg rounds, avg cost, success rate, 7-day trends.
3. **Memory:** Total skills/episodes/knowledge, creation rate, reuse rate, search rate.
4. **Behavior (0-10):** Stuck events, circuit breakers, directive compliance, commitments met/overdue, dedup blocked, avg pause before action.

**Overall consciousness score** = meta_cognition×0.30 + efficiency×0.25 + memory×0.20 + behavior×0.25

### Infrastructure
- `scripts/consciousness_metrics.py` — daily aggregator, reads events.jsonl/task_results/experiments.json/ChromaDB
- `consciousness_history.json` — daily snapshots, 30-day backfill done
- Cron job at 23:55 UTC
- Caddy routes: `/api/consciousness/*` (static JSON), `/consciousness` (HTML dashboard)

## Self-Evolution System

THAI can autonomously modify its own code through a safety pipeline.

### File Zones (config/FILE_ZONES.yaml)
- **Green:** prompts, config, tools, product code, scripts → direct commit
- **Yellow:** non-critical core (context.py, memory.py, consciousness.py, loop.py) → branch + smoke test + auto-merge
- **Red:** critical core (agent.py, supervisor/, BIBLE.md, .env, FILE_ZONES.yaml) → branch + smoke test + Shareholder review

### Safety
- 5 smoke tests before any merge (registry, context, config, imports, memory tools)
- Post-merge health check → auto-rollback if broken
- Self-modification cooldown: 3 normal tasks between self-mods
- Daily autonomous budget cap: $50.00

### Relationship to Experiment Engine
Self-Evolution (P17) handles CODE changes through file zones. Experiment Engine handles BEHAVIORAL changes through skills/knowledge. Clear boundary — they don't overlap.

## Behavioral Systems (added April 2-21, 2026)

### Amnesia Fix (Session 1)
- **Pre-panic snapshot:** `_snapshot_scratchpad_before_shutdown()` writes current state to scratchpad.md before /panic or /stop
- **Chat history injection:** Last 40 messages from chat.jsonl loaded into context after every restart
- **Restart banner:** POST-RESTART DETECTED warning prevents re-generating /plan
- **Staleness check:** Warning when scratchpad doesn't contain today's date

### Memory Protocol Hardcode (Session 2)
- **`_inject_memory_lookup_prompt()`** in loop.py: forces find_skills + memory_search before every task
- **Stuck detector** in consciousness.py: detects 3+ similar consecutive thoughts, alerts Shareholder, extends sleep to 2h

### Accountability (Session 3)
- **Message dedup** in supervisor/telegram.py: blocks >80% similar messages within 5min window
- **Directive extraction** in memory.py: auto-detects stop/pause/forget in Shareholder messages
- **Directive injection** in context.py: active directives shown at top of every task context, 24h expiry
- **Commitment tracker** in supervisor/queue.py: deadlines on planned tasks, nudge when overdue

### Task Scope Boundary (April 2)
- After successful write_file/repo_write in a write/create/rewrite task, injects completion nudge
- Prevents scope creep: THAI stops after primary task, reports deployment/testing as suggested follow-up
- Triggered by detection of action words in task + file write tool calls

### Model Routing + Scratchpad + Stuck Escalation (April 3) ✅
- **Model routing fix** (`agent.py`): Short Shareholder messages (<60→<20 threshold, `?` check, new keywords) now route to full model. "что думаешь как CEO?" → Sonnet, not flash-lite.
- **Scratchpad REPLACE** (`loop.py`): Post-task scratchpad write now REPLACES entire content (not append). Clears stale /panic "Вернулся..." banners after first task completes.
- **Stuck model escalation** (`loop.py`): After round 5, if 3 consecutive rounds have <50 completion tokens and 0 successful tool calls → escalate from flash-lite to full model. Once per task. Logs `stuck_model_escalation` event.

### Memory Core Guarantee + Observability + Whitelist Hardening (April 14-21) ✅
- **R1 — memory core guarantee** (`agent.py:423-468`, commit `08047f7`): `_ensure_memory_core()` runs before every task. If `identity.md` or `scratchpad.md` is missing or 0 bytes, writes placeholder and emits `startup_memory_restore`. Closes the 04-12 distress loop where a vanished `identity.md` was silently tolerated by every read site.
- **R5 — `chromadb_stats` tool** (`tools/semantic_memory.py:205`, commit `d6baeb8`): Read-only tool surfaces per-collection item counts + last-write timestamps so THAI can self-inspect memory state instead of inferring from retrieval failures. Brings tool total to 64.
- **D25 — consciousness whitelist hardened** (`consciousness.py:1278-1295`, commit `c9af2d1`): `update_identity` removed from the background-thread tool whitelist. The light-model cycle can no longer rewrite `identity.md`; identity-write path is now main task loop only. Closes the attack surface that corrupted identity on 04-12.

### Results (Caddy check control task)
| Stage | Rounds | Cost |
|-------|--------|------|
| Before any fixes | 13 | $0.848 |
| After memory system | 3 | $0.182 |
| After all behavioral fixes | 3 | $0.008 |

### Prism V1 Test Results (April 2)
| Text | manipulation | gaps | credibility | Correct? |
|------|-------------|------|-------------|----------|
| "Coffee cures cancer, Big Pharma furious" | 0.9 | 0.9 | 0.0 | Yes |
| "Fed held rates steady" (neutral) | 0.0 | 0.7 | 0.5 | Yes |
| "WAKE UP SHEEPLE" (conspiracy) | 0.9 | 0.9 | 0.0 | Yes |

V1 works for extreme cases. Weak spot: subtle manipulation via framing, cherry-picking, omission. This is V2 territory.

## Paused Systems

Subsystems that exist in code but are intentionally disabled. Do not re-enable without a Shareholder decision.

**Strategic Planner: paused pending redesign**
- Mechanism: kill switch via `STRATEGIC_PLANNER_ENABLED` env var (`consciousness.py:328`)
- Active since: 2026-04-11 (triage merge `e5ddd04` on ouroboros)
- Status: not to be re-enabled until redesigned
- Reason: current implementation fires every ~30min generating autonomous PlannedTasks, misaligned with current Shareholder-driven workflow
- Next step: redesign criteria TBD after baseline eval run
- Env var intentionally absent from `.env` — do not add it without Shareholder decision

## Persistent Data (~/ouroboros-data/)

```
ouroboros-data/
├── logs/           — chat.jsonl, events.jsonl, tools.jsonl, supervisor.jsonl
├── state/
│   ├── state.json
│   ├── queue_snapshot.json
│   ├── daily_budget.json
│   ├── directives.json      — active Shareholder directives (24h expiry)
│   ├── commitments.json     — tracked task commitments
│   ├── experiments.json     — experiment engine state (active + completed)
│   ├── reflected_tasks.json — tasks already reflected on
│   └── consciousness_history.json — daily metric snapshots (30-day backfill)
├── memory/
│   ├── identity.md          — THAI identity
│   ├── scratchpad.md        — current state (REPLACED after every task, snapshot on shutdown)
│   ├── wisdom.md            — distilled strategic knowledge (28KB + confirmed experiments)
│   ├── knowledge/           — topic files with _index.md
│   ├── episodic/            — daily JSONL files (experiences, skills)
│   └── .restart_marker      — written on shutdown, read on startup
├── task_results/   — JSON results per task
└── archive/        — rescue backups
```

## Governance (BIBLE.md v2.1)

**Shareholder (Sergey):** Strategic oversight, approves product direction, budget increases, constitutional changes, public launches. Reviews red-zone code changes.

**CEO (THAI):** Full operational autonomy within approved scope. Writes own code through safety pipeline. Plans own work when queue is empty. Reports to Shareholder via Telegram.

**Key rules:**
- R1: 24h production freeze after launch
- R2: No production changes without bug report or shareholder request
- R3: Plans before execution on open tasks
- R4: Single focus per task
- R5: Read INFRASTRUCTURE.md before touching services
- R6: One task, one branch

**Hard boundary:** Red-zone files (agent.py, supervisor/, BIBLE.md) require Shareholder review. THAI's autonomous workers must NOT perform refactoring or file deletion in red zone.

## Key Lessons Learned

1. **"Do what you think is right" is dangerous.** THAI spent ~$69 in one day with open-ended authority. Always set concrete scope.
2. **Autonomous agents cause real damage.** Per-task cost caps, MAX_ROUNDS, task dedup, production freeze — all from real incidents.
3. **Mocked tests miss production bugs.** Smoke tests with real calls essential.
4. **Registry bugs cascade silently.** Wrong return type in episodic_memory.py crashed entire tool registry.
5. **Text instructions get ignored — code enforcement works.** Memory Protocol in SYSTEM.md was ignored. Same protocol hardcoded in loop.py works 100%.
6. **Budget burns fast in consciousness cycles.** 22 identical cycles over 10 hours cost $0.03 but wasted time. Stuck detector now prevents this.
7. **Announcement ≠ execution.** THAI announces plans then doesn't start. Commitment tracker with deadlines closes this gap.
8. **Directives get lost in chat.** "Stop bot development" was ignored 7 minutes later. Auto-extraction + context injection fixes this.
9. **Pre-shutdown state must be saved explicitly.** /panic kills process instantly — scratchpad snapshot must happen BEFORE SystemExit.
10. **THAI is a better strategist than executor.** JTBD analysis = CEO quality. Bot deployment = 2h of loops. Strategy tasks should use full context; execution tasks should have lower MAX_ROUNDS and early escalation.
11. **Autonomous self-modification breaks things.** THAI committed a broken stub function that caused NameError crashing all task execution. Red-zone files require Shareholder approval. Always have unit tests with assertions and acceptance gate before merging.
12. **Scope creep kills budgets.** Task "rewrite prompt" took 25 rounds — wrote file at round 11, spent 14 rounds testing/deploying. Task scope boundary fix prevents this.
13. **Flash-lite gets stuck silently.** Returns tiny responses (11 tokens) that aren't empty, so fallback doesn't trigger. Loops 25 rounds. Stuck model escalation now detects and fixes this.
14. **Model routing determines task quality.** "что думаешь как CEO?" on flash-lite → "Вернулся..." garbage. Same question on Sonnet → coherent strategy. Short message ≠ simple task. Always consider question marks, keywords, and context.
15. **Stale scratchpad poisons all tasks.** /panic banner in scratchpad persists across tasks, causing flash-lite to output "Вернулся..." even mid-conversation. Post-task REPLACE (not append) clears the poison.

## Workflow

- **Claude Code:** Implementation sessions (code changes, server work, debugging). SSH into server directly.
- **Claude.ai chat:** Strategy, design reviews, architecture decisions, behavioral analysis, session planning.
- **Telegram:** Communication with THAI when running. Directives auto-extracted.

## Current Priorities

1. **Prism V2:** Test on "gray zone" articles (subtle manipulation via framing, cherry-picking). If V1 fails → rewrite analyze_text prompt.
2. **Validate 3 behavioral fixes** — test model routing, scratchpad freshness, stuck escalation on live THAI.
3. **Let THAI accumulate skills organically** — skill lifecycle + experiment engine now active.
4. **Budget management:** ~$58 remaining, ~$3-5/day operational cost.
5. **Future:** SLM fine-tuning on accumulated skills/reflections (month 2-3).

## Implementation History

**Phase 1 (Feb 2026): AI Company** — Multi-agent CrewAI system. Discovery Crew selected VendorLens. CEO Dashboard built. ~$12 spent.

**Phase 2 (Mar 2026): THAI/Ouroboros** — Pivoted to autonomous CEO. THAI built and deployed VendorLens. BIBLE.md v2.0 written. 439 tasks, $253.89 spent. Governance hardened after incidents.

**Phase 3 (Mar-Apr 2026): Memory + Behavioral Systems** — 6 Claude Code sessions transformed THAI from amnesiac executor to self-improving CEO with persistent memory, skill reuse, stuck detection, directive compliance, and accountability tracking. Control task improved from 13 rounds/$0.85 to 3 rounds/$0.008.

**Phase 4 (Apr 2-3, 2026): Meta-Cognition + Observability** — Skill Lifecycle System (auto-extraction, dedup, validation, 26 tests). Experiment Engine (pattern detection, hypothesis generation, measurement, auto-revert, 44 tests). Consciousness Dashboard (4-dimension tracking, 30-day backfill, daily cron). Task scope boundary. Server cleanup (ai-company archived). BIBLE.md amended to v2.1 with P17 Self-Evolution. Model routing fix + scratchpad REPLACE + stuck model escalation (3 fixes in one branch). Prism V1 validated on 3 test texts — works for extreme cases, V2 needed for gray zone.
