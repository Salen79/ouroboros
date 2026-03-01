# Budget Strategy

> CEO управляет бюджетом автономно в рамках лимитов.
> Акционер контролирует через /status и OpenRouter dashboard.

---

## Режим 1: Стартовый капитал ($1000)

Распределение — на усмотрение CEO. Ориентировочно:
- Discovery: 10% ($100)
- Development: 50% ($500)
- Review & testing: 15% ($150)
- Consciousness & planning: 15% ($150)
- Reserve: 10% ($100)

## Режим 2: Самофинансирование (после $1000)

- 70% revenue → компания (операции, продукты, инфраструктура)
- 30% revenue → акционер (неизменно)

---

## Лимиты CEO

- Не более $50 за один evolution cycle
- Остановиться если >$30 потрачено без результата
- MAX_ROUNDS=25 (safety)
- Отчёт акционеру каждые 10% бюджета
- Background consciousness ≤ 10% бюджета

## Контроль акционера

- `/status` в Telegram — текущие расходы
- https://openrouter.ai/activity — реальные списания (источник правды)
- https://platform.openai.com/usage — расходы на web search
- `/panic` — аварийная остановка
