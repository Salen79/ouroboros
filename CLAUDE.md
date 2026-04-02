# THAI — Autonomous AI CEO (Ouroboros)

## What This Is

THAI (Truly Human AI) is an autonomous AI agent that operates as CEO of a virtual company. It communicates via Telegram, makes operational decisions independently, builds and deploys products, and reports to a single human Shareholder (Sergey). The project is built on the Ouroboros self-evolving agent framework.

**The mission:** Contributing to the growth of human consciousness on Earth — through products that create genuine value. This is a learning platform for AI organization risk management, not just product delivery.

**Constitution:** BIBLE.md v2.0 + P17 (Self-Evolution) — based on Bob Chapman's Truly Human Leadership principles. This is THAI's soul and the governance contract between THAI and the Shareholder.

## Current State (April 2, 2026)

**Products:**
- **VendorLens** (vendorlens.app) — AI-powered vendor/pricing page analysis SaaS. Live in production. Strategically paused (doesn't align with P0). FastAPI backend, Next.js frontend, PostgreSQL, Caddy.
- **Prism** — Media/content bias analysis. Telegram bot (@Prism_analzer_bot) + web backend. Early stage. JTBD redefined: not "political position scores" but "am I being manipulated? what's missing? why was this written this way?" — direct P0 alignment.

**THAI status:** Running. Budget $68 / $400 (83% spent). Total tasks completed: ~450+.

**Active focus:** Prism V2 (rewrite analyze_text prompt for manipulation detection), Self-Evolution System integration.

**Recently completed:**
- Memory System — all 3 sessions done (semantic search, skills, auto-reflection, context optimization)
- Behavioral Fixes — 3 sessions done (amnesia fix, memory hardcode, accountability)
- Self-Evolution System — installed (file zones, smoke tests, strategic planning)

## Architecture

```
Telegram → colab_launcher.py → supervisor/ → agent.py → LLM (OpenRouter)
                                    │
                                    ├── workers.py     (up to 5 parallel)
                                    ├── consciousness.py (background reflection + stuck detector + commitment check)
                                    ├── queue.py       (task queue + CommitmentTracker)
                                    └── events.py      (event bus → events.jsonl)

ouroboros/
  ├── agent.py          — thin orchestrator
  ├── consciousness.py  — background cycle: reflection, stuck detection, commitment nudges
  ├── context.py        — prompt assembly + chat history injection + directive injection + restart banner
  ├── loop.py           — tool loop (MAX_ROUNDS=25) + memory protocol injection + progress tracking
  ├── llm.py            — OpenRouter client
  ├── memory.py         — scratchpad, identity, chat, directive extraction
  ├── self_evolution.py — file zone enforcement + merge pipeline
  ├── strategic_planner.py — autonomous goal-setting for consciousness.py
  ├── tools/            — auto-discovered plugins (62 total, 39 core)
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
  ├── memory_stats.py   — ChromaDB + episodic stats
  └── evolution_stats.py — self-modification metrics
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

### Service Management
```bash
sudo systemctl status vendorlens-backend vendorlens-frontend caddy prism-backend prism-bot
sudo journalctl -u vendorlens-backend -f
docker compose -f ~/ai-company/docker-compose.yml ps
```

### SSH Access
```bash
ssh -p 2222 deploy@38.180.135.77
```

## Git

- **Remote:** github.com:Salen79/ouroboros, branch `ouroboros`
- **Product code:** `company/vendor-lens/` (backend + frontend)
- **Agent code:** `ouroboros/`, `supervisor/`, `prompts/`
- **Archived:** ~/ai-company/ (CrewAI experiment, frozen)

**Warning:** `colab_launcher.py` runs `git checkout ouroboros && git reset --hard origin/ouroboros` on startup. All uncommitted changes will be wiped. Always commit and push before starting THAI.

## THAI Configuration

### Environment (~/ouroboros/.env)
```
OPENROUTER_API_KEY=      # Multi-model API
TELEGRAM_BOT_TOKEN=      # THAI Telegram bot
TOTAL_BUDGET=400         # OpenRouter budget cap (USD)
GITHUB_TOKEN=            # GitHub with repo rights
OUROBOROS_MAX_ROUNDS=25  # Hard limit per task
OUROBOROS_MAX_TASK_COST=5.00   # USD per task cap
OUROBOROS_CONSCIOUSNESS_COST_CAP=0.10  # USD per consciousness cycle
OUROBOROS_DAILY_AUTO_CAP=50.00  # Daily autonomous spending cap
```

### Models (via OpenRouter)
| Role | Model |
|------|-------|
| Primary | anthropic/claude-sonnet-4.6 |
| Code editing | anthropic/claude-sonnet-4.6 |
| Light (consciousness, dedup) | google/gemini-2.5-flash-lite |
| Web search | gpt-5 (OpenAI Responses API) |
| Fallback chain | Claude Sonnet → Gemini Pro → GPT-4.1 |

### Safety Mechanisms
| Mechanism | Parameter | Action |
|-----------|-----------|--------|
| Per-task cost cap | $5.00 | Hard stop, decompose |
| Consciousness cost cap | $0.10 | Skip cycle |
| MAX_ROUNDS | 25 | Hard stop, decompose |
| Circuit breaker | 3 empty responses | Hard stop |
| Task dedup | >50% keyword overlap | Skip |
| Budget checkpoints | 25/50/75/90% | Report to shareholder |
| Stuck detector | 3 similar thoughts | Alert + extend sleep to 2h |
| Message dedup | >80% similarity in 5min | Skip duplicate outgoing message |
| Directive compliance | Shareholder stop/pause/forget | Inject into all task contexts |
| Commitment tracker | Planned tasks with deadlines | Nudge when overdue |
| Memory protocol (code-enforced) | find_skills + memory_search | Auto-injected before every task |
| Pre-panic snapshot | scratchpad overwrite | Saves state before /panic or /stop |
| Chat history injection | Last 40 messages | Loaded into context after restart |

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

## Memory System

### Architecture
| Layer | Tool | Storage |
|-------|------|---------|
| Working memory | scratchpad.md | File (auto-consolidation >8000 chars) |
| Identity | identity.md | File |
| Strategic knowledge | wisdom.md | File (28KB) |
| Knowledge base | knowledge_read/write | Files in knowledge/ (index only loaded, ~1.5K tokens) |
| Episodic memory | record_memory, memory_search | JSONL files + ChromaDB |
| Skills | save_skill, find_skills | JSONL + ChromaDB (semantic search) |
| History RAG | recall | ChromaDB (483+ chat/event chunks) |
| Semantic search | semantic_search, semantic_find_skills | ChromaDB |
| Recent chat | _load_recent_chat(40) | chat.jsonl → context injection |

### Memory Protocol (code-enforced in loop.py)
Before every task: `find_skills()` + `memory_search()` are injected as mandatory first steps.
After tasks >3 rounds: system logs that skill save is warranted.
Auto-reflection runs in consciousness.py after task completion.

### ChromaDB Collections
| Collection | Entries | Purpose |
|-----------|---------|---------|
| thai_episodes | 55+ | Insights, decisions, errors |
| thai_skills | 3+ | Proven procedures |
| thai_history | 483+ | Chat and event chunks |

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

## Behavioral Systems (added April 2, 2026)

### Amnesia Fix (Session 1)
- **Pre-panic snapshot:** `_snapshot_scratchpad_before_shutdown()` writes current state (last tasks, recent chat, shutdown reason) to scratchpad.md before /panic or /stop
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

### Execution Quality (Session 4)
- **Plan-Before-Execute** (`_inject_plan_before_execute_prompt()`) in loop.py: detects action words (implement, build, rewrite, напиши, сделай, создай, etc.) and injects mandatory planning prompt before any tool calls
- **Circular Loop Detector** (`_LoopDetector` class) in loop.py: tracks file re-reads (2+ files re-read after round 5) and low-output patterns (3 consecutive rounds with completion < 200 tokens, context > 30K) — injects "STOP NOW" message
- **Post-Task Scratchpad Write** (`_post_task_scratchpad_write()`) in loop.py: appends task summary (description, rounds, cost, result length, status) to scratchpad.md after every task; warns on possible silent failure (result < 100 chars after > 10 rounds)

### Results (Caddy check control task)
| Stage | Rounds | Cost |
|-------|--------|------|
| Before any fixes | 13 | $0.848 |
| After memory system | 3 | $0.182 |
| After all behavioral fixes | 3 | $0.008 |

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
│   └── reflected_tasks.json — tasks already reflected on
├── memory/
│   ├── identity.md          — THAI identity
│   ├── scratchpad.md        — current working notes (auto-snapshot on shutdown)
│   ├── wisdom.md            — distilled strategic knowledge (28KB)
│   ├── knowledge/           — topic files with _index.md
│   ├── episodic/            — daily JSONL files (experiences, skills)
│   └── .restart_marker      — written on shutdown, read on startup
├── task_results/   — JSON results per task
└── archive/        — rescue backups
```

## Governance (BIBLE.md v2.0 + P17)

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

## Workflow

- **Claude Code:** Implementation sessions (code changes, server work, debugging). SSH into server directly.
- **Claude.ai chat:** Strategy, design reviews, architecture decisions, behavioral analysis, session planning.
- **Telegram:** Communication with THAI when running. Directives auto-extracted.

## Current Priorities

1. **Prism V2:** Rewrite analyze_text prompt — from position scores to manipulation/omission/credibility detection
2. **Let THAI accumulate skills organically** — memory system working, skills grow with usage
3. **Budget management:** $68 remaining, ~$3-5/day operational cost
4. **Future:** SLM fine-tuning on accumulated skills/reflections (month 2-3)

## Historical Context

**Phase 1 (Feb 2026): AI Company** — Multi-agent CrewAI system. Discovery Crew selected VendorLens. CEO Dashboard built. ~$12 spent.

**Phase 2 (Mar 2026): THAI/Ouroboros** — Pivoted to autonomous CEO. THAI built and deployed VendorLens. BIBLE.md v2.0 written. 439 tasks, $253.89 spent. Governance hardened after incidents.

**Phase 3 (Mar-Apr 2026): Memory + Behavioral Systems** — 6 Claude Code sessions transformed THAI from amnesiac executor to self-improving CEO with persistent memory, skill reuse, stuck detection, directive compliance, and accountability tracking. Control task improved from 13 rounds/$0.85 to 3 rounds/$0.008.
