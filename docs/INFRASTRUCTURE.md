# Infrastructure — Что есть на сервере

> VPS: ISHosting USA (New York)
> IP: 38.180.135.77 | SSH port: 2222 | User: deploy
> OS: Ubuntu 24.04 | 4 vCPU Xeon / 8 GB RAM / 50 GB SSD

---

## Доступные сервисы (Docker Compose)

| Сервис | Порт | Статус | Назначение |
|--------|------|--------|------------|
| PostgreSQL 16 | 5432 (localhost) | ✅ Running | Основная БД |
| Redis 7 | 6379 (localhost) | ✅ Running | Кэш, pub/sub, очереди |
| ChromaDB | 8000 (localhost) | ✅ Running | Vector storage для RAG |

Все сервисы доступны только через localhost (не открыты наружу).
Docker Compose файл: `~/ai-company/docker-compose.yml`

```bash
# Управление сервисами
cd ~/ai-company
docker compose up -d          # Запустить всё
docker compose ps             # Статус
docker compose logs chromadb  # Логи конкретного сервиса
docker compose down           # Остановить
```

---

## Код AI Company (CrewAI)

**Расположение:** `~/ai-company/`

### Что уже работает
- **Discovery Crew** (4 агента): Market Researcher, Opportunity Analyst, Product Strategist, Risk Assessor
- **FastAPI Bridge** на порту 8001 — middleware между CrewAI и Dashboard
- **CEO Dashboard** (Next.js) на порту 3000 — веб-интерфейс мониторинга
- **Budget Controller** — 3-tier thresholds (50% warning, 80% alert, 95% hard stop)
- **Circuit Breaker** — защита от runaway (3 пустых ответа → стоп)
- **30 тестов** — unit tests для budget, circuit breaker, token tracking

### Ключевые файлы
```
~/ai-company/
├── src/ai_company/
│   ├── main.py                  # CLI entry point
│   ├── config/
│   │   ├── agents.yaml          # 4 агента Discovery crew
│   │   └── tasks.yaml           # Задачи агентов
│   ├── crews/discovery/crew.py  # DiscoveryCrew implementation
│   └── utils/
│       ├── budget.py            # BudgetController
│       ├── circuit_breaker.py   # CircuitBreaker + PipelineTimeout
│       ├── dashboard_bridge.py  # FastAPI bridge (:8001)
│       └── crewai_callbacks.py  # Event handlers
├── ceo-dashboard/               # Next.js CEO Dashboard v2.0
├── tests/                       # 30 тестов
├── outputs/                     # Результаты прошлых прогонов
└── .env                         # API ключи (НЕ в git)
```

### Запуск Discovery crew
```bash
cd ~/ai-company
docker compose up -d                              # Инфраструктура
uv run python -m ai_company.main --crew discovery  # Pipeline
```

### Результаты прошлых прогонов
| # | Дата | Продукт | Стоимость | Статус |
|---|------|---------|-----------|--------|
| 1 | 2026-02-16 | VendorLens | ~$2-3 | APPROVED (CEO Gate 1) |
| 2 | 2026-02-21 | CodeLens Docs | ~$0.24 | Test run |
| 3 | 2026-02-21 | CodeSensei | $0.24 | 25.9k tokens, 4 min |
| 4 | 2026-02-22 | Integration test | $0.26 | Score 10/10 |

Подробные результаты: `~/ai-company/outputs/`

---

## Порты

| Порт | Сервис | Доступ |
|------|--------|--------|
| 2222 | SSH | Внешний (ключ deploy) |
| 3000 | CEO Dashboard (Next.js) | localhost (SSH tunnel) |
| 5432 | PostgreSQL | localhost only |
| 6379 | Redis | localhost only |
| 8000 | ChromaDB | localhost only |
| 8001 | FastAPI Bridge | localhost only |

**⚠️ Bridge на :8001, НЕ :8000** — ChromaDB занимает :8000.

---

## Доступ с Mac (CEO)

```bash
# SSH с туннелями для Dashboard
ssh -p 2222 -L 3000:localhost:3000 -L 8001:localhost:8001 deploy@38.180.135.77
```

---

## API-ключи

Файл: `~/ai-company/.env` (не в git)

| Переменная | Назначение |
|-----------|------------|
| `ANTHROPIC_API_KEY` | Claude models (Opus, Sonnet, Haiku) |
| `OPENAI_API_KEY` | GPT-5.2, web search |
| `SERPER_API_KEY` | Web search для CrewAI |
| `OPENROUTER_API_KEY` | Мультимодельный доступ (для Ouroboros) |

---

## Модели доступные через API

| Модель | API String | Цена (in/out per MTok) |
|--------|-----------|------------------------|
| Claude Opus 4.6 | `anthropic/claude-opus-4-6` | $5 / $25 |
| Claude Sonnet 4.5 | `anthropic/claude-sonnet-4-5-20250929` | $3 / $15 |
| GPT-5.2 | `openai/gpt-5.2` | $1.75 / $14 |
| Claude Haiku 4.5 | `anthropic/claude-haiku-4-5-20251001` | $1 / $5 |

Через OpenRouter доступны все модели всех провайдеров.

---

## Безопасность

- SSH: только ключевая аутентификация, нестандартный порт 2222
- UFW firewall: открыты только 2222 (SSH) и 80/443 (для будущих продуктов)
- fail2ban: защита от брутфорса
- Все БД: только localhost, не открыты наружу
- .env: не в git, скопирован отдельно
