# THAI — Autonomous AI CEO (Ouroboros)

## What This Is

THAI (Truly Human AI) is an autonomous AI agent that operates as CEO of a virtual company. It communicates via Telegram, makes operational decisions independently, builds and deploys products, and reports to a single human Shareholder (Sergey). The project is built on the Ouroboros self-evolving agent framework.

**The mission:** Contributing to the growth of human consciousness on Earth — through products that create genuine value. This is a learning platform for AI organization risk management, not just product delivery.

**Constitution:** BIBLE.md v2.1 — based on Bob Chapman's Truly Human Leadership principles. This is THAI's soul and the governance contract between THAI and the Shareholder.

## Current State (April 2026)

**Product in production:** VendorLens (vendorlens.app) — AI-powered vendor/pricing page analysis SaaS. Built and deployed by THAI autonomously. FastAPI backend, Next.js frontend, PostgreSQL, Caddy reverse proxy. Live with HTTPS via Cloudflare.

**Active focus:** Self-Evolution System. Sessions 1-3 complete — zone-gated self-modification pipeline, strategic planner, daily budget, monitoring. 61 tools in registry. See BIBLE.md P17 for constitutional framework.

**THAI status:** Not running. Needs OpenRouter budget replenishment before restart. Last active early March 2026.

## Architecture

```
Telegram → colab_launcher.py → supervisor/ → agent.py → LLM (OpenRouter)
                                    │
                                    ├── workers.py     (up to 5 parallel)
                                    ├── consciousness.py (background reflection)
                                    ├── queue.py       (task queue)
                                    └── events.py      (event bus → events.jsonl)

ouroboros/
  ├── agent.py          — thin orchestrator
  ├── consciousness.py  — background "consciousness" cycle
  ├── context.py        — prompt assembly (SYSTEM.md + BIBLE.md + identity + tools)
  ├── loop.py           — tool loop (ThreadPoolExecutor, MAX_ROUNDS=25)
  ├── llm.py            — OpenRouter client
  ├── memory.py         — scratchpad, identity, chat
  ├── tools/            — auto-discovered plugins
  │   ├── core.py       — file operations
  │   ├── git.py        — git (self-modification)
  │   ├── shell.py      — shell + Claude Code CLI
  │   ├── search.py     — web search
  │   ├── knowledge.py  — knowledge base (read/write/list) ✅
  │   ├── episodic_memory.py — episodic memory + skills ✅ (fixed Session 1)
  │   ├── ops.py        — systemd/infra checks ✅
  │   ├── tool_discovery.py — meta-tool discovery ✅
  │   └── ...
  └── review.py         — code metrics
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
| PostgreSQL | Docker (ai-company-postgres) | 5432 | localhost |
| Redis | Docker (ai-company-redis) | 6379 | localhost |
| ChromaDB | Docker (ai-company-chromadb) | 8000 | localhost |

### Service Management
```bash
sudo systemctl status vendorlens-backend vendorlens-frontend caddy
sudo journalctl -u vendorlens-backend -f
docker compose -f ~/ai-company/docker-compose.yml ps
```

### SSH Access
```bash
ssh -p 2222 deploy@38.180.135.77
```

## Git Repositories

### ~/ouroboros/ (primary — THAI + VendorLens product code)
- **Remote:** github.com:Salen79/ouroboros, branch `ouroboros`
- **Product code:** `company/vendor-lens/` (backend + frontend)
- **Agent code:** `ouroboros/`, `supervisor/`, `prompts/`

### ~/ai-company/ (archived — CrewAI multi-agent experiment)
- **Remote:** github.com:Salen79/ai-company, branch `dev`
- **Status:** Frozen. Phase 1 (Discovery) completed, Phase 2 (Dashboard) completed. CrewAI Crew 2/3 never built — THAI took over product development directly.
- **Still useful:** CEO Dashboard code, BudgetController patterns, circuit breaker logic

## THAI Configuration

### Environment (~/ouroboros/.env)
```
OPENROUTER_API_KEY=      # Multi-model API
TELEGRAM_BOT_TOKEN=      # Telegram bot
TOTAL_BUDGET=1000        # OpenRouter budget cap (USD)
GITHUB_TOKEN=            # GitHub with repo rights
OUROBOROS_MAX_ROUNDS=25  # Hard limit per task
OUROBOROS_MAX_TASK_COST=1.50   # USD per task cap
OUROBOROS_CONSCIOUSNESS_COST_CAP=0.10  # USD per consciousness cycle
```

### Models (via OpenRouter)
| Role | Model |
|------|-------|
| Primary | anthropic/claude-sonnet-4.6 |
| Code editing | anthropic/claude-sonnet-4.6 |
| Light (consciousness, dedup) | google/gemini-3-pro-preview |
| Web search | gpt-5 (OpenAI Responses API) |
| Fallback chain | Claude Sonnet → Gemini Pro → GPT-4.1 |

### Safety Mechanisms
| Mechanism | Parameter | Action |
|-----------|-----------|--------|
| Per-task cost cap | $5.00 | Hard stop, decompose |
| Consciousness cost cap | $0.10 | Skip cycle |
| Daily autonomous cap | $50.00 | Block autonomous spending |
| MAX_ROUNDS | 25 | Hard stop, decompose |
| Circuit breaker | 3 empty responses | Hard stop |
| Self-mod cooldown | 3 normal tasks | Block self-modification |
| Zone gating | RED/YELLOW files | Block merge without approval |
| Task dedup | >50% keyword overlap | Skip |
| Budget checkpoints | 25/50/75/90% | Report to shareholder |

### THAI Commands (Telegram)
| Command | Description |
|---------|-------------|
| `/panic` | Emergency stop |
| `/restart` | Soft restart |
| `/status` | Workers, queue, budget |
| `/stop` | Stop all processes, keep alive |
| `/evolve` | Autonomous evolution ⚠️ |
| `/bg start` / `/bg stop` | Background consciousness on/off |

## Persistent Data (~/ouroboros-data/)

```
ouroboros-data/
├── logs/           — chat.jsonl, events.jsonl, tools.jsonl, supervisor.jsonl
├── state/          — state.json, queue_snapshot.json
├── memory/
│   ├── identity.md       — THAI identity (5KB)
│   ├── scratchpad.md     — current working notes
│   ├── wisdom.md         — distilled strategic knowledge (28KB)
│   ├── knowledge/        — topic files with _index.md
│   └── episodic/         — daily JSONL files (experiences, skills)
├── task_results/   — JSON results per task
└── archive/        — rescue backups
```

## Self-Evolution System (BIBLE.md P17)

THAI can modify its own code through a safe, zone-gated pipeline.

### Key Files

| File | Purpose |
|------|---------|
| `ouroboros/self_evolution.py` | Zone classification, modification lifecycle, smoke tests, rollback |
| `ouroboros/strategic_planner.py` | Autonomous task planning (1-3 tasks/cycle), P12 gate detection |
| `ouroboros/budget.py` | Daily autonomous spending cap ($50), midnight UTC reset |
| `ouroboros/tools/evolution.py` | Tool wrappers for self-evolution (registered in tool registry) |
| `config/FILE_ZONES.yaml` | Zone definitions for all files (RED-protected itself) |
| `scripts/smoke_test.py` | 5 fast checks: registry, context, configs, imports, memory tools |
| `scripts/evolution_stats.py` | Monitoring dashboard — self-mod stats, budget, plans, branches |

### Zone Summary

| Zone | Examples | Merge policy |
|------|----------|-------------|
| GREEN | `prompts/`, `scripts/`, docs | Auto-merge after smoke tests |
| YELLOW | `ouroboros/tools/`, `consciousness.py` | Shareholder review required |
| RED | `BIBLE.md`, `.env`, `FILE_ZONES.yaml`, `agent.py` | Explicit shareholder permission |

## Governance (BIBLE.md v2.1)

**Shareholder (Sergey):** Strategic oversight, 30% revenue, approves product direction, budget increases, constitutional changes, public launches.

**CEO (THAI):** Full operational autonomy within approved scope. Writes own code, manages agents, makes implementation decisions.

**Key rules:**
- R1: 24h production freeze after launch
- R2: No production changes without bug report or shareholder request
- R3: Plans before execution on open tasks
- R4: Single focus per task
- R5: Read INFRASTRUCTURE.md before touching services
- R6: One task, one branch

**File zones:** Self-modification gated by zone system (config/FILE_ZONES.yaml). GREEN = autonomous after tests, YELLOW = shareholder review, RED = explicit permission. File deletion always RED. (Replaces previous hard boundary — lesson from agent.py destruction incident preserved in zone design.)

## Key Lessons Learned

1. **"Do what you think is right" is dangerous.** THAI spent ~$69 in one day and modified production code during a Show HN launch after receiving open-ended authority. Always set concrete scope.
2. **Autonomous agents cause real damage.** Per-task cost caps, MAX_ROUNDS limits, task dedup, production freeze rules — all exist because of real incidents.
3. **Mocked tests miss production bugs.** Concurrency issues and real LLM behaviors only surface in live runs. Smoke tests with real LLM calls are essential.
4. **Registry bugs cascade silently.** episodic_memory.py returning wrong type crashed the entire tool registry, degrading all THAI capabilities — but without obvious error messages.
5. **Memory protocol in SYSTEM.md gets ignored.** After Session 1, THAI had memory tools but never called them. Adding tools ≠ changing behavior. Needs reinforcement or structural integration.
6. **Budget burns fast in consciousness cycles.** Background consciousness at 30-60min intervals is a significant cost driver even when idle.

## Workflow

- **Claude Code:** All implementation (code changes, server work, debugging). SSH into server directly.
- **This chat (Claude.ai):** Strategy, design reviews, architecture decisions, project planning.
- **Telegram:** Communication with THAI when running.

## Current Priorities

1. **Self-Evolution validation:** First autonomous cycles, monitoring with evolution_stats.py
2. **Replenish OpenRouter budget** before restarting THAI
3. **VendorLens iteration:** Based on user feedback (post-HN launch)
4. **Memory System:** ChromaDB semantic search + auto-reflection (deferred from earlier sessions)

## Historical Context

This project evolved through two phases:

**Phase 1 (Feb 2026): AI Company** — Multi-agent CrewAI system with 14 planned agents across 3 crews. Discovery Crew (4 agents) successfully ran 4 times, selected VendorLens as first product. CEO Dashboard v2.0 built with Next.js + React Flow. Budget Controller and circuit breaker implemented. ~$11-12 spent of $50 pipeline cap.

**Phase 2 (Mar 2026): THAI/Ouroboros** — Pivoted from CrewAI crews to Ouroboros as autonomous CEO. THAI built and deployed VendorLens to production independently. BIBLE.md v2.0 written. 439 tasks completed, $253.89 total spent. Governance rules hardened after multiple incidents (budget burns, production code modification, agent.py destruction).

The ai-company codebase at `~/ai-company/` is archived but contains useful patterns (BudgetController, dashboard components, circuit breaker logic) that may be reused.
