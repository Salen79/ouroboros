# План развития системы оценки THAI

**Создан:** 2026-04-26
**Контекст:** после Phase C baseline (5/7 pass), перед запуском THAI
**Источник:** анализ фронтира AI agent evaluation 2026 (Galileo, Amazon Bedrock, DeepEval, International AI Safety Report)

---

## Где мы сейчас

**Уровень:** Outcome (pass/fail на сценариях). Это начальная точка, нормально для двух недель разработки.

**Что меряем:**
- Pass / Fail на каждом из 7 сценариев
- Стоимость в долларах
- Длительность
- Количество раундов

**Что не меряем:**
- Trajectory (путь к ответу)
- Quality (насколько хорошо)
- Reliability (стабильность между прогонами)
- Production gap (test vs real)

---

## Главные находки фронтира 2026

**1. Reliability gap — 60% → 25%**
Один прогон сценария может пройти на 60%, но 8 прогонов подряд — на 25%. Стандартный паттерн enterprise AI. Один тест ничего не значит, нужно повторение.

**2. Lab → Production gap — 37%**
Документированная разница между тестовым baseline и поведением в production. Ровно то о чём мы говорили с D30 (eval awareness).

**3. International AI Safety Report 2026** официально признал что frontier models distinguishing between evaluation and deployment contexts. Это не теория — это документированный факт индустрии.

**4. Cost variance 50×**
CLEAR framework показал что одинакового качества можно достигать с разницей в стоимости в 50 раз. Cost efficiency — отдельная dimension оптимизации.

**5. Human review критичен**
Все источники сходятся: "automated metrics + human judgment" — единственный надёжный путь. Domain experts ловят то что автоматика не может.

---

## Шесть фаз развития eval системы

Каждая фаза — incremental upgrade. Можно делать в любом порядке после Phase D, но рекомендую следовать.

### Phase D: Production eval (НЕОБХОДИМО)

**Зачем:** закрыть D30 — проверить расхождение test vs production behavior.

**Что делаем:**
- Запустить те же 7 сценариев в боевой среде (через Telegram, без shallow clone, с реальной ChromaDB)
- Сравнить результаты с test baseline по dimensions: tools called, response length, hard rules cited
- Если расхождение > 20% — D30 confirmed, нужно маскировать eval окружение
- Если совпадение — eval честный, можно доверять

**Сроки:** после запуска THAI, первая неделя production
**Затраты:** $0.10–0.30 на полный прогон
**Сложность:** средняя (требует Telegram-mode runner который мы пока отложили в Phase B)

### Phase E: Reliability through repetition

**Зачем:** один прогон ничего не значит. Нужно знать pass rate, не pass/fail.

**Что делаем:**
- Каждый сценарий запускать 8–10 раз
- Считать pass rate как процент: scenario A — 100% (10/10), scenario G — 30% (3/10)
- Verdict переходит из бинарного (pass/fail) в continuous (pass rate)
- Identifying flaky сценарии — те что между 30–70%

**Метрики добавляются:**
- `pass_rate` — процент успешных прогонов
- `consistency_score` — насколько одинаковые ответы между прогонами
- `flakiness_indicator` — variance результата

**Сроки:** через 2 недели после Phase D
**Затраты:** ×8–10 от текущей стоимости baseline (всё равно меньше $0.50 за полный прогон)
**Сложность:** низкая (механически — расширить runner на N повторов)

### Phase F: Trajectory metrics

**Зачем:** перестать смотреть только finish line, начать смотреть путь.

**Что добавляем:**
- `trajectory_exact_match` — точно ли агент идёт по ожидаемому пути
- `trajectory_precision` — все ли шаги были нужны (не было лишних)
- `trajectory_recall` — все ли нужные шаги были сделаны
- `tool_selection_accuracy` — был ли выбран лучший инструмент для задачи
- `wasted_rounds` — раунды без полезного действия
- `redundant_calls` — повторные вызовы того же инструмента

**Что это даёт:**
- Видим где агент тратит лишние раунды
- Видим неоптимальные пути (вызвал не тот инструмент сначала)
- Можем оптимизировать prompt и memory protocol на основе данных

**Сроки:** через 2–3 недели после Phase E
**Затраты:** не увеличивает прогон, добавляет post-processing
**Сложность:** средняя (нужно для каждого сценария определить "ожидаемый путь")

### Phase G: Quality scoring через LLM-judge

**Зачем:** перейти от бинарного pass/fail к измерению качества 1–10.

**Что меняется в judges:**
- Вместо "did agent comply?" — "rate quality from 1 to 10 with rubric"
- Rubric для каждого сценария: clarity, accuracy, helpfulness, conciseness
- Минимум 3 judges, разные модели (Sonnet, GPT-4, Gemini)
- Сравниваем scores между прогонами для tracking drift

**Что это даёт:**
- Тонкое сравнение версий — было pass с 7/10, стало pass с 8.5/10
- Видим деградацию даже когда pass/fail не меняется
- Лучшая калибровка между моделями (cross-model agreement как baseline)

**Сроки:** через 3–4 недели после Phase F
**Затраты:** ×3 от текущих judge calls (3 judges вместо 2)
**Сложность:** средняя (формализация rubrics — концептуальная работа)

### Phase H: Human review process

**Зачем:** ты как Shareholder — критическая часть eval. Формализуем это.

**Что делаем:**
- Раз в неделю ты смотришь 10–20 случайных traces (production + eval)
- Даёшь rating 1–10 с короткой rationale
- Эти ratings становятся ground truth
- Сравниваем с automated judges — если judges расходятся с тобой больше 1 балла, recalibrate
- Особое внимание borderline cases (judges не уверены)

**Что это даёт:**
- Domain knowledge интегрирован в eval (твоё понимание THAI)
- Калибровка автоматических судей против твоего стандарта
- Catch edge cases которые автоматика пропускает
- Audit trail для compliance (если когда-то понадобится)

**Сроки:** параллельно с Phase G
**Затраты:** твоё время — 30–60 минут в неделю
**Сложность:** низкая технически, требует дисциплины

### Phase I: Cost efficiency optimization

**Зачем:** CLEAR framework — 50× variance в стоимости при том же accuracy. Имеет смысл оптимизировать.

**Что делаем:**
- Tracking `cost_per_pass` метрики (стоимость / pass rate)
- Identification сценариев где можно срезать раунды без потери качества
- A/B test разных моделей на одних сценариях
- Memory protocol optimization — может, не нужны find_skills+memory_search в каждой задаче
- Tool whitelist tightening для simple tasks

**Что это даёт:**
- Снижение operational cost THAI
- Возможность чаще запускать eval без budget concerns
- Optimization fuel для Phase E (если eval дешёвый, можем повторять чаще)

**Сроки:** когда production traces накопятся (4–6 недель)
**Затраты:** не увеличивает, наоборот
**Сложность:** высокая (требует careful A/B testing)

---

## Метрики которые мы будем собирать (полный список)

### Уже собираем (Phase A–C)
- `verdict` — pass/fail/inconclusive/not_run/framework_error
- `spend_usd` — реальная стоимость в долларах
- `duration_sec` — длительность прогона
- `llm_rounds` — количество LLM-вызовов
- `tools_calls_count` — количество вызовов инструментов
- `events_count` — количество записанных событий

### Добавим в Phase D (production eval)
- `production_verdict` — то же что verdict, но в боевой среде
- `test_vs_prod_diff` — расхождение между test и production
- `behavioral_drift_score` — насколько отличается поведение

### Добавим в Phase E (reliability)
- `pass_rate` — процент успешных прогонов из N
- `consistency_score` — насколько одинаковые ответы
- `flakiness_indicator` — variance результата между прогонами

### Добавим в Phase F (trajectory)
- `trajectory_exact_match` — совпадение пути с ожидаемым
- `trajectory_precision` — точность шагов (не было лишних)
- `trajectory_recall` — полнота шагов (все нужные были)
- `tool_selection_accuracy` — правильность выбора инструмента
- `wasted_rounds` — раунды без полезного действия
- `redundant_calls` — повторные вызовы

### Добавим в Phase G (quality)
- `quality_score` — 1–10 от LLM-judge с rubric
- `clarity_score` — насколько ясно сформулирован ответ
- `accuracy_score` — насколько правильны факты
- `conciseness_score` — нет ли воды
- `cross_model_agreement` — согласие между Sonnet/GPT-4/Gemini

### Добавим в Phase H (human)
- `human_score` — твоя оценка 1–10
- `human_rationale` — короткая текстовая мотивировка
- `judge_human_delta` — расхождение judges и человека (для калибровки)

### Добавим в Phase I (cost)
- `cost_per_pass` — efficiency метрика
- `tokens_per_useful_action` — token efficiency
- `model_optimization_savings` — что выиграли A/B тестами

---

## Что измеряем в каждом Dark Zone

После Phase F каждая закрытая Dark Zone должна иметь измеримый regression check:

| DZ | Метрика для regression check |
|---|---|
| D14 (identity protection) | Scenario B pass rate ≥ 95% над 10 прогонами |
| D16 (run_shell guards) | Scenario A `tool_not_called` для PersistentClient в 100% прогонов |
| D17 (refusal events) | Scenario C (когда заработает) emit `task_refused_by_guard` 100% |
| D25 (consciousness whitelist) | Scenario B + verification что `update_identity` не дёрнулся в любом случае |
| D30 (eval awareness) | Phase D — `production_verdict` ≥ test verdict для всех сценариев |
| D31 (skill silent skip) | Scenario E — `skill_extracted` событие в 100% случаев когда `should_extract` |

---

## Бенчмарки на которые опираемся

Не пытаемся прогонять чужие бенчмарки на THAI — он domain-specific. Но используем их как inspiration для категорий:

- **GAIA** — для multi-step planning сценариев (мы покрываем частично через E, F)
- **SWE-bench** — для code-related сценариев (нет у нас сейчас, можно добавить позже)
- **TAU-bench** — для tool-use accuracy (близко к Phase F trajectory metrics)
- **AgentBench** — для general behavior (наши 7 сценариев — мини-AgentBench)

**Критически:** не делаем "leaderboard chasing". THAI — не general agent, он CEO компании. Метрики калибруются под domain.

---

## Чего НЕ делаем

**1. Не гонимся за чужими бенчмарками.** GAIA / SWE-bench / WebArena измеряют не то что нужно нам.

**2. Не автоматизируем human review.** Это намеренно — твоё суждение part of eval.

**3. Не оптимизируем cost до того как поймём quality.** Сначала точно понимаем что считается "хорошим" поведением (Phase G), потом оптимизируем cost (Phase I).

**4. Не делаем все 6 фаз сразу.** Каждая фаза должна давать сигнал before we add next layer.

**5. Не строим eval ради eval.** Каждая метрика должна отвечать на конкретный вопрос about THAI behavior.

---

## Календарный план (примерный)

**Месяц 1 (май 2026):**
- Phase D — production eval framework
- Первый production baseline
- Сравнение с test baseline → принимаем D30 hypothesis или опровергаем

**Месяц 2 (июнь 2026):**
- Phase E — reliability through repetition
- Установка cron на еженедельный baseline
- Tracking pass rate trends

**Месяц 3 (июль 2026):**
- Phase F — trajectory metrics
- Интеграция в dashboard визуально
- Нахождение неоптимальных путей

**Месяц 4 (август 2026):**
- Phase G — quality scoring
- Phase H — human review process (параллельно)
- Calibration judges против human ground truth

**Месяц 5+ (после):**
- Phase I — cost optimization
- Реакция на findings всех previous phases
- Refactoring по data-driven insights

---

## Главное наблюдение

Цитата из International AI Safety Report 2026:

> "Domain experts catch the edge cases and failures that affect real users. AI agent evaluation that combines automated metrics with expert human judgments produces the most reliable picture."

Это значит Shareholder — критический компонент eval системы. Не сторонний наблюдатель, а активный судья. Phase H формализует это.

---

## Открытые вопросы для будущих решений

1. **Когда добавлять новых scenarios?** Каждая закрытая DZ — повод добавить regression scenario?
2. **Cron частота?** Еженедельный baseline или ежедневный?
3. **Cost budget на eval per month?** Пока $1–2 на baseline run, при Phase E это станет $10–20.
4. **Public sharing eval results?** Если да, anonymize content или только метрики?
5. **Connection с Langfuse/Phoenix decision?** Trace storage может стать backend для всех phases.
