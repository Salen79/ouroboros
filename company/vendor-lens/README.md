# VendorLens

> AI-powered vendor contract & dependency analyzer for indie developers.  
> Paste a vendor URL → get pricing analysis, risk flags, and side-by-side comparison in 60 seconds.

**Status:** MVP in development  
**Mission:** Decision clarity — turn hours of vendor research into a structured 60-second decision.

---

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12 + FastAPI (port 8002) |
| Frontend | Next.js 14 + Tailwind CSS + shadcn/ui (port 3001) |
| Database | PostgreSQL 16 (existing Docker, localhost:5432) |
| LLM | OpenRouter API (GPT-4o primary, Claude 3.5 fallback) |
| Scraping | Jina Reader (https://r.jina.ai/{url}) |

---

## Quick Start

### Backend

```bash
cd backend
cp .env.example .env     # fill in your keys
pip install -e .          # or: uv sync
uvicorn app.main:app --reload --port 8002
```

### Frontend

```bash
cd frontend
cp .env.local.example .env.local
npm install
npm run dev -- --port 3001
```

### Both (with Make)

```bash
make install
make dev
```

---

## Environment Variables

### Backend (`backend/.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | ✅ | `postgresql+asyncpg://ai_company:PASSWORD@localhost:5432/ai_company` |
| `OPENROUTER_API_KEY` | ✅ | OpenRouter API key (sk-or-...) |
| `STRIPE_SECRET_KEY` | ⚡ | Stripe secret key (sk_test_... for dev) |
| `STRIPE_WEBHOOK_SECRET` | ⚡ | Stripe webhook signing secret |
| `FRONTEND_URL` | ✅ | `http://localhost:3001` |
| `JINA_API_KEY` | ❌ | Optional — for higher Jina rate limits |
| `DEBUG` | ❌ | `true` in development |

### Frontend (`frontend/.env.local`)

| Variable | Required | Description |
|----------|----------|-------------|
| `NEXT_PUBLIC_API_URL` | ✅ | `http://localhost:8002` |

---

## API Endpoints

```
GET  /health                          — Health check
POST /api/vendors/analyze             — Analyze a vendor URL
GET  /api/vendors/{id}                — Get saved vendor analysis
POST /api/comparisons/create          — Compare 2-3 vendors
GET  /api/comparisons/{id}            — Get saved comparison
GET  /api/comparisons/share/{token}   — Public share link
POST /api/reports/export              — Export comparison (Markdown/PDF)
```

---

## Pricing Model (V1)

| Tier | Price | Analyses/mo |
|------|-------|-------------|
| Free | $0 | 3 |
| Indie | $29 | 20 |
| Team | $79 | 100 (5 seats) |
| Pro | $149 | Unlimited |

---

## Project Structure

```
vendor-lens/
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI app entry
│   │   ├── config.py         # Settings (pydantic-settings)
│   │   ├── database.py       # SQLAlchemy async
│   │   ├── models.py         # DB models
│   │   ├── schemas.py        # Pydantic schemas
│   │   ├── routers/          # API routes
│   │   └── services/         # Business logic (scraper, analyzer, comparator)
│   ├── pyproject.toml
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── app/              # Next.js App Router pages
│   │   ├── components/       # React components
│   │   └── lib/              # API client, types
│   ├── package.json
│   └── .env.local.example
├── docker-compose.yml
└── Makefile
```
