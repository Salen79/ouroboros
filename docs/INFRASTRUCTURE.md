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

## Docker Compose (~/ouroboros/infra/)

```bash
docker compose -f ~/ouroboros/infra/docker-compose.yml ps
```

## AI Company (archived)

Мульти-агентная система на CrewAI — archived 2026-04-02.
Archive: `~/archive/ai-company-2026-02.tar.gz` (447M)

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

## Environment Variables

API keys managed in `~/ouroboros/.env`

---

## VendorLens Production

### VendorLens Services

| Сервис | Порт | Systemd unit |
|--------|------|--------------|
| Backend (FastAPI/uvicorn) | 8100 | vendorlens-backend.service |
| Frontend (Next.js) | 3000 | vendorlens-frontend.service |
| PostgreSQL | 5432 | (Docker: ai-company-postgres) |
| Caddy | 80/443 | caddy.service |

### Database Access

```bash
docker exec ai-company-postgres psql -U ai_company -d vendorlens
```

### Domain

vendorlens.app (Cloudflare DNS, SSL Full Strict)

---

## Границы (из BIBLE.md P9)

CEO может делать всё на сервере кроме:
- Менять SSH-конфигурацию или firewall
- Открывать порты наружу без согласования с акционером
- Удалять архив ~/archive/ (историческая ценность)
