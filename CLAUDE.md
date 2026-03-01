# Ouroboros v6.2.0 — Self-Evolving AI Agent

## What this is

Ouroboros is a self-evolving AI agent running as CEO of an autonomous AI company.
Deployed on VPS (Ubuntu 24.04). Communicates with creator (Sergey, shareholder) via Telegram.

## Key roles

- **Ouroboros** — CEO, autonomous decision-maker
- **Sergey (Salen79)** — Shareholder, sole owner, first Telegram contact

## Directory layout

```
~/ouroboros/                    — Main repo (this directory)
├── colab_launcher.py           — Entry point (starts supervisor + main loop)
├── ouroboros/                   — Core agent (agent, loop, tools, LLM, memory)
├── supervisor/                  — Process management (state, telegram, queue, workers, git_ops, events)
├── prompts/SYSTEM.md            — System prompt
├── BIBLE.md                     — Constitution (DO NOT MODIFY without explicit permission)
├── docs/                        — Strategy & landing page (DO NOT MODIFY without explicit permission)
├── company/vendor-lens/         — VendorLens product (SaaS vendor analysis)
├── ai-company -> ~/ai-company/  — CrewAI multi-agent company (symlink)
├── .env                         — Secrets and config (NEVER commit, NEVER print)
└── tests/                       — Test suite

~/ouroboros-data/                — Runtime data (state, logs, memory)
├── state/state.json             — Persistent state (owner, budget, version)
├── logs/                        — chat.jsonl, events.jsonl, supervisor.jsonl
└── memory/                      — scratchpad.md, identity.md
```

## Constraints from .env

- `OUROBOROS_MAX_WORKERS=1` — single worker mode
- `OUROBOROS_MAX_ROUNDS=25` — max LLM rounds per task
- `OUROBOROS_BG_BUDGET_PCT=10` — background consciousness budget cap
- `TOTAL_BUDGET=1000` — total USD budget

## Tech stack

- Python 3.12, OpenRouter API (Claude Sonnet 4.6 primary)
- Telegram Bot API for communication
- GitHub (Salen79/ouroboros) for code persistence
- Local filesystem for state (no Google Drive)

## Rules

- **NEVER** expose secrets from `.env` in logs, commits, chat, or files
- **NEVER** modify SSH config, firewall, ports, or system services
- **NEVER** modify BIBLE.md or docs/ without explicit creator permission
- **NEVER** run `env`, `printenv`, or commands that dump environment variables
- Constitution is in `BIBLE.md` — read it before making architectural decisions
- All commits go to `main` branch
