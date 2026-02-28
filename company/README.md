# company/ — Product Portfolio

This directory is where the AI Company builds its products.

## Mission

This company exists to support and develop life on Earth by building
products that help people live more consciously, freely, and intentionally.
See BIBLE.md for the full constitution.

## Server Environment

Products run on VPS (ISHosting USA, New York). Available infrastructure:
- Docker with PostgreSQL 16, Redis 7, ChromaDB
- Python 3.11.9 + uv package manager
- Node.js + npm (for Next.js frontends)
- CrewAI framework (4 Discovery agents operational)
- CEO Dashboard (Next.js + React Flow) on :3000
- See docs/INFRASTRUCTURE.md for full details

## Rules

1. **All product code goes here** — backend, frontend, API, configs
2. **Agent code (ouroboros/, supervisor/) stays untouched** unless a bug blocks product development
3. **Tests are mandatory** — nothing ships without passing tests
4. **Mission filter** — every product must pass: "Does this help people live more consciously?"
5. **Can use existing infra** — Docker services, CrewAI agents, Dashboard as needed

## Lifecycle

Each product gets its own subdirectory:

```
company/
├── product-1/        # First product (built with $1000 starter)
│   ├── backend/
│   ├── frontend/
│   ├── tests/
│   └── README.md
├── product-2/        # Second product (self-funded from revenue)
│   └── ...
└── shared/           # Shared libraries across products (if any)
```

## Financial model

- First product: funded by $1000 starter capital
- All subsequent products: funded by 70% of company revenue
- 30% of all revenue goes to the creator (non-negotiable)
- Company must be self-sustaining before starting product #2
