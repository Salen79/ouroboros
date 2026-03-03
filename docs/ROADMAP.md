# ROADMAP — Эволюция компании

> Стартовый бюджет: $1000 (единственная внешняя инвестиция)
> После $1000 — компания живёт на собственный доход (70/30 split)
> CEO (Ouroboros) определяет КАК. Акционер (Sergey) определяет ЧТО.

---

## === ПЕРВЫЙ ПРОДУКТ: VendorLens ===

**Статус:** Product Brief одобрен акционером 28 февраля 2026.
Scaffold создан. Backend в разработке.

### Phase 1: Discovery ✅ COMPLETE ($2.43)

- [x] Изучил BIBLE.md и docs/
- [x] Изучил результаты 4 Discovery runs
- [x] Отверг CodeGate (конкурент Stacklok, Copilot threat)
- [x] Выбрал VendorLens с переформулировкой "decision clarity"
- [x] Product Brief → **SHAREHOLDER GATE 1: APPROVED**

### Phase 2: Foundation (в процессе)

CEO решает как строить. Текущий план:
- [x] Scaffold: backend (FastAPI) + frontend (Next.js) + Docker
- [x] Pydantic schemas, SQLAlchemy models
- [x] Services: scraper, analyzer, comparator
- [x] Routers: health, analysis, comparison
- [ ] Рабочий backend с реальными LLM вызовами
- [ ] Деплой на сервере, доступен по URL
- [ ] **SHAREHOLDER GATE 2:** акционер тестирует MVP

### Phase 3: Product

- [ ] Все 5 MVP-фич работают
- [ ] Landing page
- [ ] Error handling
- [ ] **SHAREHOLDER GATE 3:** ready for users?

### Phase 4: Users

- [ ] SEO, Product Hunt, Hacker News
- [ ] Первые 10 пользователей
- [ ] Feedback loop

### Phase 5: Monetization

- [ ] Stripe интеграция
- [ ] **SHAREHOLDER GATE 4 (Pricing):** модель монетизации
- [ ] Первый доллар дохода
- [ ] Автоматический split: 70% компания / 30% акционер

---

## === ПЕРЕХОД К САМОФИНАНСИРОВАНИЮ ===

После исчерпания $1000:

**Если revenue есть:** компания продолжает на 70%.
**Если revenue нет:** CEO отчитывается акционеру, акционер решает.

---

## === ПОСЛЕ ПЕРВОГО ПРОДУКТА ===

### Phase 6: Stabilize & Grow
- Автоматизация поддержки первого продукта
- Рост revenue до стабильного MRR
- Накопление резервного фонда

### Phase 7+: Следующие продукты
- CEO проводит Discovery
- Product Brief → Shareholder Gate
- Build → Ship → Grow → Monetize

---

## Shareholder Gates (точки контроля акционера)

| Gate | Что решает акционер | Когда |
|------|---------------------|-------|
| Product Gate | Какой продукт строить | После Discovery |
| Launch Gate | Готов ли к публичному запуску | После MVP |
| Pricing Gate | Модель монетизации и цены | Перед Stripe |
| Pivot Gate | Смена направления | При необходимости |

Всё остальное — операционные решения CEO.
