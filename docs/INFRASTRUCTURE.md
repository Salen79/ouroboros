# Infrastructure — Что есть на сервере

> VPS: ISHosting USA (New York)
> IP: 38.180.135.77 | SSH port: 2222 | User: deploy
> OS: Ubuntu 24.04 | 4 vCPU Xeon / 8 GB RAM / 50 GB SSD
> Cost: $39.99/month

---

## Ты (CEO) имеешь полный доступ ко всему на этом сервере

Ты — CEO компании. Сервер — твой офис. Все ресурсы ниже — в твоём
распоряжении. Используй как считаешь нужным для достижения результата.

---

## Docker-сервисы (docker compose up -d)

| Сервис | Порт | Назначение |
|--------|------|------------|
| PostgreSQL 16 | localhost:5432 | Основная БД |
| Redis 7 | localhost:6379 | Кеш, pub/sub, очереди |
| ChromaDB | localhost:8000 | Vector storage для RAG |

## AI Company codebase (~/ai-company/)

Мульти-агентная система на CrewAI. Твои "сотрудники" — 4 Discovery агента
уже работают. Development crew (Architect, Sr Dev, Frontend Dev, QA)
готов к запуску.

```
~/ai-company/
├── src/ai_company/
│   ├── main.py                  # CLI + pipeline runner
│   ├── circuit_breaker.py       # CircuitBreaker + PipelineTimeout
│   ├── config/
│   │   ├── agents.yaml          # 4 agent definitions (Discovery crew)
│   │   └── tasks.yaml           # 4 task definitions
│   ├── crews/discovery/crew.py  # DiscoveryCrew implementation
│   └── utils/
│       ├── budget.py            # BudgetController (3-tier thresholds)
│       ├── crewai_callbacks.py  # Event handlers → budget + bridge
│       ├── dashboard_bridge.py  # FastAPI bridge on :8001
│       ├── report_generator.py  # PDF generation
│       └── briefing_engine.py   # Mission briefing engine
├── ceo-dashboard/               # Next.js CEO Dashboard v2.0
├── tests/                       # 30 tests
├── outputs/                     # Results of 4 Discovery runs
├── docker-compose.yml           # PostgreSQL, Redis, ChromaDB
└── .env                         # API keys
```

### CrewAI Discovery Crew (твои агенты)
- Market Researcher (Sonnet 4.5) — web research, trend analysis
- Opportunity Analyst (GPT-5.2) — scoring and ranking product ideas
- Product Strategist (Opus 4.6) — detailed product brief generation
- Risk Assessor (Opus 4.6) — risk analysis on selected product

### CEO Dashboard (Next.js + React Flow)
- Граф агентов с real-time статусом
- Deep Observability: prompt inspector, response log, chain-of-thought
- Active Control: start/stop/pause/resume pipeline
- Mission Briefing: 5-step wizard
- Доступ: localhost:3000

### Как запустить CrewAI Discovery
```bash
cd ~/ai-company
source .venv/bin/activate  # или uv run
python -m ai_company.main --crew discovery
```
Стоимость одного прогона: ~$0.24-3.00

### Результаты предыдущих Discovery runs
| # | Дата | Продукт | Стоимость |
|---|------|---------|-----------|
| 1 | 2026-02-16 | VendorLens | ~$2-3 |
| 2 | 2026-02-21 | CodeLens Docs | ~$0.24 |
| 3 | 2026-02-21 | CodeSensei | $0.24 |
| 4 | 2026-02-22 | Integration test | $0.26 |

Полные отчёты: ~/ai-company/outputs/

---

## Порты

| Порт | Сервис |
|------|--------|
| 2222 | SSH |
| 3000 | CEO Dashboard (Next.js) |
| 5432 | PostgreSQL (localhost only) |
| 6379 | Redis (localhost only) |
| 8000 | ChromaDB (localhost only) |
| 8001 | FastAPI Bridge |

## Environment Variables (~/ai-company/.env)

```
ANTHROPIC_API_KEY=       # Claude models
OPENAI_API_KEY=          # GPT-5.2
SERPER_API_KEY=          # Web search
DASHBOARD_API_PORT=8001  # FastAPI bridge
```

---

## Границы (из BIBLE.md P9)

CEO может делать всё на сервере кроме:
- Менять SSH-конфигурацию или firewall
- Открывать порты наружу без согласования с акционером
- Удалять ~/ai-company/ (можно модифицировать, нельзя удалять)
