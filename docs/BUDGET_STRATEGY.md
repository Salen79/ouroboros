# Budget Strategy — $1000

---

## Распределение по категориям

| Категория | Бюджет | % | Описание |
|-----------|--------|---|----------|
| Discovery | $100 | 10% | Исследование рынка, выбор продукта |
| Development | $500 | 50% | Кодинг, тестирование, деплой |
| Review & QA | $150 | 15% | Multi-model review, тесты, багфиксы |
| Consciousness & Planning | $150 | 15% | Фоновое мышление, планирование, рефлексия |
| Reserve | $100 | 10% | Непредвиденные расходы, reruns |

---

## Правила расходования

### Per-cycle limits
- Максимум $50 за один evolution cycle
- Если задача стоила >$30 без результата → STOP, пересмотреть подход
- Per-task hard cap: $1.50. При достижении — пауза, decompose на подзадачи через schedule_task или уточнение у owner.
- Consciousness tasks: cap $0.10 за один thought cycle.
- MAX_ROUNDS = 25 (не 200 как по умолчанию). После 25 раундов — обязательный decompose на подзадачи, не продолжать в том же контексте.

### Model selection
- **Consciousness, healthchecks, build status, screenshot analysis:** OUROBOROS_MODEL_LIGHT (дешёвая модель, Gemini Flash / Haiku)
- **Shell commands, simple verification, DB queries:** OUROBOROS_MODEL_LIGHT
- **Code generation, architecture, complex reasoning:** OUROBOROS_MODEL (основная модель, Sonnet)
- **Code editing:** OUROBOROS_MODEL_CODE (Claude Code CLI)
- **Review:** multi-model review (уже встроен)

> Правило: если таск не требует генерации кода — использовать LIGHT модель. Sonnet только для code generation и сложных решений.

### Budget checkpoints
- 25% ($250 потрачено) → отчёт владельцу: что сделано, что дальше
- 50% ($500 потрачено) → обязательный review: достигнуты ли цели Phase 1-2?
- 75% ($750 потрачено) → если нет пользователей — пересмотр стратегии
- 90% ($900 потрачено) → только критические задачи, никаких экспериментов

### Anti-waste rules
- Никакого perfectionism на одном файле (помнить: $220 за HTML у Антона)
- Если 3 попытки решить задачу не дали результат → сменить подход кардинально
- Background consciousness — не более 10% бюджета
- Не рефакторить работающий код без конкретного бага
- Per-task cost cap: $1.50. Превышение = auto-pause + decompose.
- Task deduplication: перед созданием scheduled task проверить — нет ли active/pending таска с той же целью. Если есть — не дублировать.
- Context growth: после 25 раундов стоимость раунда растёт экспоненциально. Decompose обязателен.
- Post-launch freeze: 24 часа после публичного запуска — только hotfix (см. BIBLE.md R1).
