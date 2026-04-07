"""Deep Reflection tool — анализ событий и диалога за указанный период.

Реальный формат events.jsonl:
  - task_received: {"ts":..., "type":"task_received", "task":{"id":..., "text":...}}
  - task_done:     {"ts":..., "type":"task_done", "task_id":..., "cost_usd":..., "total_rounds":...}
  - llm_round:     {"ts":..., "type":"llm_round", "task_id":..., "round":..., "cost_usd":...}
  - llm_empty_response: {"ts":..., "type":"llm_empty_response", ...}
  - ops_check, consciousness_thought, auto_reflection, ...

Реальный формат chat.jsonl:
  {"ts":..., "direction":"in"/"out", "text":..., "chat_id":..., "user_id":...}
"""

import json
import logging
import os
import pathlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from ouroboros.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)

DRIVE_ROOT = os.environ.get("DRIVE_ROOT", os.path.expanduser("~/ouroboros-data"))


# ---------------------------------------------------------------------------
# Период
# ---------------------------------------------------------------------------

def _parse_period(period_str: Optional[str]) -> Tuple[datetime, datetime]:
    """Парсит строку периода и возвращает (start, end) в UTC.

    Поддерживаемые форматы:
    - None / ""         → последний час
    - "1h" / "last_hour"→ последний час
    - "today" / "сегодня" → с 00:00 UTC сегодня
    - "2h"              → последние 2 часа
    - "24h" / "day"     → последние 24 часа
    - "7d" / "week"     → последние 7 дней
    - "Xh" / "Xd"       → последние X часов / дней
    """
    now = datetime.now(timezone.utc)

    if not period_str:
        return now - timedelta(hours=1), now

    p = period_str.strip().lower()

    if p in ("today", "сегодня"):
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now

    if p in ("yesterday", "вчера"):
        yesterday = now - timedelta(days=1)
        start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        end = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
        return start, end

    if p in ("last_hour", "1h", "час", "last hour"):
        return now - timedelta(hours=1), now

    if p in ("day", "день", "24h"):
        return now - timedelta(hours=24), now

    if p in ("week", "неделя", "7d"):
        return now - timedelta(days=7), now

    # "Xh" или "Xd"
    if p.endswith("h") and p[:-1].isdigit():
        return now - timedelta(hours=int(p[:-1])), now

    if p.endswith("d") and p[:-1].isdigit():
        return now - timedelta(days=int(p[:-1])), now

    # Неизвестный формат — последний час
    log.warning("deep_reflection: unknown period '%s', defaulting to last hour", period_str)
    return now - timedelta(hours=1), now


# ---------------------------------------------------------------------------
# Чтение файлов
# ---------------------------------------------------------------------------

def _read_jsonl(filepath: str, tail: int = 1000) -> List[dict]:
    """Читает последние `tail` строк JSONL файла без загрузки всего в память."""
    path = pathlib.Path(filepath)
    if not path.exists():
        log.warning("deep_reflection: file not found: %s", filepath)
        return []
    try:
        text = path.read_text(encoding="utf-8")
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if len(lines) > tail:
            lines = lines[-tail:]
        result = []
        for line in lines:
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return result
    except Exception as exc:
        log.warning("deep_reflection: failed to read %s: %s", filepath, exc)
        return []


def _parse_ts(ts_raw: Any) -> Optional[datetime]:
    """Парсит timestamp разных форматов в datetime с tzinfo=UTC."""
    if ts_raw is None:
        return None
    try:
        if isinstance(ts_raw, (int, float)):
            return datetime.fromtimestamp(ts_raw, tz=timezone.utc)
        ts_str = str(ts_raw)
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts_str)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _filter_by_period(entries: List[dict], start: datetime, end: datetime) -> List[dict]:
    """Фильтрует записи по временному диапазону (ищет поле ts/timestamp/created_at)."""
    result = []
    for entry in entries:
        ts_raw = entry.get("ts") or entry.get("timestamp") or entry.get("created_at")
        ts = _parse_ts(ts_raw)
        if ts and start <= ts <= end:
            result.append(entry)
    return result


# ---------------------------------------------------------------------------
# Анализ событий
# ---------------------------------------------------------------------------

def _analyze_events(events: List[dict]) -> dict:
    """Анализирует события из events.jsonl по реальным типам."""

    # Собираем task_received для маппинга task_id → описание
    task_descriptions: Dict[str, str] = {}
    for e in events:
        if e.get("type") == "task_received":
            task = e.get("task", {})
            tid = task.get("id", "")
            text = str(task.get("text", ""))[:80]
            if tid:
                task_descriptions[tid] = text

    tasks_done: List[dict] = []
    tasks_max_rounds: List[dict] = []
    tool_errors = 0
    llm_empty = 0
    ops_checks = 0
    total_cost = 0.0
    llm_rounds_total = 0

    # Считаем tool-вызовы по именам инструментов
    tool_counts: Dict[str, int] = {}

    for e in events:
        etype = e.get("type", "")

        if etype == "task_done":
            tid = e.get("task_id", "")
            rounds = e.get("total_rounds", 0)
            cost = e.get("cost_usd", 0.0)
            total_cost += cost
            desc = task_descriptions.get(tid, tid[:20] if tid else "?")

            # task_done с total_rounds == MAX_ROUNDS (12) — вероятно принудительная остановка
            # (флаг success отсутствует в логах, поэтому проверяем по rounds)
            entry = {
                "task_id": tid[:12],
                "description": desc,
                "rounds": rounds,
                "cost_usd": cost,
                "hit_max_rounds": rounds >= 12,
            }
            if rounds >= 12:
                tasks_max_rounds.append(entry)
            else:
                tasks_done.append(entry)

        elif etype == "llm_round":
            total_cost += e.get("cost_usd", 0.0)
            llm_rounds_total += 1

        elif etype == "llm_empty_response":
            llm_empty += 1

        elif etype in ("tool_error", "tool_warning", "tool_timeout"):
            tool_errors += 1

        elif etype == "ops_check":
            ops_checks += 1

        # Инструменты из tool_call событий (если есть)
        elif etype == "tool_call":
            tool_name = e.get("tool_name") or e.get("name") or "unknown"
            tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1

    return {
        "tasks_done": tasks_done,
        "tasks_max_rounds": tasks_max_rounds,
        "total_cost": total_cost,
        "llm_rounds_total": llm_rounds_total,
        "llm_empty": llm_empty,
        "tool_errors": tool_errors,
        "ops_checks": ops_checks,
        "tool_counts": tool_counts,
        "total_events": len(events),
    }


# ---------------------------------------------------------------------------
# Анализ чата
# ---------------------------------------------------------------------------

def _analyze_chat(chat_entries: List[dict]) -> dict:
    """Анализирует диалог из chat.jsonl (формат: direction=in/out)."""
    incoming: List[str] = []  # от Sergey (direction=in)
    outgoing: List[str] = []  # от THAI (direction=out)

    for entry in chat_entries:
        direction = entry.get("direction", "")
        text = str(entry.get("text", ""))[:200]
        if direction == "in":
            incoming.append(text)
        elif direction == "out":
            outgoing.append(text)

    return {
        "sergey_count": len(incoming),
        "thai_count": len(outgoing),
        "sergey_messages": incoming[-5:],  # последние 5
        "thai_messages": outgoing[-3:],
    }


# ---------------------------------------------------------------------------
# Конституционный аудит
# ---------------------------------------------------------------------------

def _assess_constitution(analysis: dict, chat: dict) -> List[str]:
    """Краткий аудит соответствия конституции P8/P15/P21."""
    issues: List[str] = []

    # P8: дорогие задачи
    all_tasks = analysis["tasks_done"] + analysis["tasks_max_rounds"]
    expensive = [t for t in all_tasks if t["cost_usd"] > 2.0]
    if expensive:
        issues.append(f"P8 Бюджет: {len(expensive)} задач дороже $2 — проверить декомпозицию")

    # P15: MAX_ROUNDS
    if analysis["tasks_max_rounds"]:
        n = len(analysis["tasks_max_rounds"])
        issues.append(f"P15 Circuit breaker: {n} задач остановлены по MAX_ROUNDS — признак циклов")

    # Пустые ответы LLM
    if analysis["llm_empty"] >= 3:
        issues.append(f"P15 Empty responses: {analysis['llm_empty']} пустых ответов — возможная проблема модели")

    # Ошибки инструментов
    if analysis["tool_errors"] >= 3:
        issues.append(f"Инструменты: {analysis['tool_errors']} ошибок — проверить конфигурацию")

    # P21: language drift (грубая эвристика по исходящим сообщениям)
    english_drift = 0
    for msg in chat.get("thai_messages", []):
        words = msg.split()[:20]
        eng = sum(1 for w in words if w.isalpha() and all(ord(c) < 128 for c in w))
        if eng > 12:
            english_drift += 1
    if english_drift:
        issues.append(f"P21 Language drift: {english_drift} сообщений с возможным English — проверить")

    return issues if issues else ["Нарушений не обнаружено ✅"]


# ---------------------------------------------------------------------------
# Генерация топ-3 действий
# ---------------------------------------------------------------------------

def _generate_actions(analysis: dict, constitution_issues: List[str]) -> List[str]:
    """Генерирует до 3 конкретных действий на основе анализа."""
    actions: List[str] = []

    # Декомпозиция задач с MAX_ROUNDS
    if analysis["tasks_max_rounds"]:
        t = analysis["tasks_max_rounds"][0]
        actions.append(
            f"Декомпозировать '{t['description'][:40]}' — "
            f"задача дошла до MAX_ROUNDS ({t['rounds']} раундов, ${t['cost_usd']:.2f})"
        )

    # Конституционные нарушения
    real_issues = [i for i in constitution_issues if "не обнаружено" not in i]
    if real_issues:
        actions.append(f"Устранить: {real_issues[0][:80]}")

    # Общие действия если мало конкретных
    defaults = [
        "Запустить run_ops_check → убедиться что Prism и VendorLens здоровы",
        "Обновить identity.md → отразить события текущего периода",
        "Проверить knowledge base → добавить уроки последних задач",
    ]
    for d in defaults:
        if len(actions) >= 3:
            break
        actions.append(d)

    return actions[:3]


# ---------------------------------------------------------------------------
# Главная функция
# ---------------------------------------------------------------------------

def _deep_reflect(ctx: ToolContext, period: str = "", **kwargs) -> str:
    """Выполняет структурированную рефлексию за указанный период."""

    # Путь к данным
    drive_root = pathlib.Path(
        ctx.drive_root if hasattr(ctx, "drive_root") and ctx.drive_root else DRIVE_ROOT
    )
    events_path = str(drive_root / "logs" / "events.jsonl")
    chat_path = str(drive_root / "logs" / "chat.jsonl")
    state_path = str(drive_root / "state" / "state.json")

    # ─── Шаг 1: Период ───────────────────────────────────────────────────────
    period_start, period_end = _parse_period(period)
    period_label = (
        f"{period_start.strftime('%Y-%m-%d %H:%M')} — "
        f"{period_end.strftime('%H:%M')} UTC"
    )

    # ─── Шаг 2: Чтение данных ────────────────────────────────────────────────
    all_events = _read_jsonl(events_path, tail=2000)
    all_chat = _read_jsonl(chat_path, tail=500)

    # ─── Шаг 3: Фильтрация ───────────────────────────────────────────────────
    period_events = _filter_by_period(all_events, period_start, period_end)
    period_chat = _filter_by_period(all_chat, period_start, period_end)

    # Fallback: если за период ничего нет — берём последние записи
    insufficient_data = False
    fallback_used = False

    if not period_events and not period_chat:
        insufficient_data = True
        if all_events or all_chat:
            fallback_used = True
            period_events = all_events[-100:]
            period_chat = all_chat[-30:]
            period_label += " (⚠️ нет данных за период, показаны последние записи)"

    # ─── Шаг 4: Анализ ───────────────────────────────────────────────────────
    event_analysis = _analyze_events(period_events)
    chat_analysis = _analyze_chat(period_chat)
    constitution_issues = _assess_constitution(event_analysis, chat_analysis)

    # ─── Шаг 5: Бюджет ───────────────────────────────────────────────────────
    budget_remaining = "?"
    budget_period_cost = event_analysis["total_cost"]
    try:
        state = json.loads(pathlib.Path(state_path).read_text())
        spent = state.get("spent_usd", 0)
        total = state.get("total_usd", 500)
        budget_remaining = f"${total - spent:.2f}"
    except Exception:
        pass

    # ─── Шаг 6: Если совсем нет данных ───────────────────────────────────────
    if insufficient_data and not fallback_used:
        return (
            f"📭 РЕФЛЕКСИЯ {period_label}\n\n"
            f"Недостаточно данных для анализа: файлы events.jsonl и chat.jsonl "
            f"не содержат записей за указанный период ({period or 'последний час'}). "
            f"Возможные причины: система только запустилась, период слишком маленький, "
            f"или файлы не заполнены. "
            f"Попробуй период 'today' или 'day' для более широкого охвата."
        )

    # ─── Шаг 7: Форматирование результата ─────────────────────────────────────
    lines = [f"🔍 РЕФЛЕКСИЯ {period_label}", ""]

    # Выполненные задачи
    done = event_analysis["tasks_done"]
    lines.append(f"✅ ВЫПОЛНЕНО ({len(done)} задач)")
    if done:
        for t in done[:8]:
            lines.append(f"• [{t['task_id']}] {t['description']} | {t['rounds']}r / ${t['cost_usd']:.3f}")
    else:
        lines.append("• Завершённых задач за период не найдено")
    lines.append("")

    # Задачи остановленные MAX_ROUNDS
    mr = event_analysis["tasks_max_rounds"]
    lines.append(f"⛔ MAX_ROUNDS ({len(mr)} задач остановлены принудительно)")
    if mr:
        for t in mr[:5]:
            lines.append(f"• [{t['task_id']}] {t['description']} | {t['rounds']}r / ${t['cost_usd']:.3f}")
    else:
        lines.append("• Принудительных остановок не было ✅")
    lines.append("")

    # Конституция
    lines.append("⚖️ КОНСТИТУЦИЯ")
    for issue in constitution_issues:
        lines.append(f"• {issue}")
    lines.append("")

    # Метрики
    lines.append("📊 МЕТРИКИ")
    lines.append(f"• Бюджет периода: ~${budget_period_cost:.3f} | Остаток: {budget_remaining}")
    lines.append(f"• LLM раундов: {event_analysis['llm_rounds_total']} | Пустых ответов: {event_analysis['llm_empty']}")
    lines.append(f"• Ошибки инструментов: {event_analysis['tool_errors']} | Ops checks: {event_analysis['ops_checks']}")
    lines.append(f"• Диалог: {chat_analysis['sergey_count']} сообщений от Sergey, {chat_analysis['thai_count']} от THAI")
    lines.append(f"• Событий в периоде: {event_analysis['total_events']}")
    lines.append("")

    # Топ-3 действия
    lines.append("🎯 ДЕЙСТВИЯ")
    actions = _generate_actions(event_analysis, constitution_issues)
    for i, action in enumerate(actions, 1):
        lines.append(f"{i}. {action}")

    result = "\n".join(lines)

    # Гарантия минимальной длины (100 символов)
    if len(result) < 100:
        result += (
            "\n\n[Данных за период мало — рекомендуется использовать период 'today' или 'day' "
            "для получения более полной картины активности системы.]"
        )

    log.info("deep_reflection: completed, result_len=%d chars, period=%s", len(result), period or "1h")
    return result


# ---------------------------------------------------------------------------
# Registry entry
# ---------------------------------------------------------------------------

def get_tools():
    return [
        ToolEntry(
            "deep_reflection",
            {
                "name": "deep_reflection",
                "description": (
                    "Выполняет глубокую рефлексию за указанный период: "
                    "анализирует events.jsonl и chat.jsonl, показывает выполненные задачи, "
                    "задачи остановленные MAX_ROUNDS, конституционный аудит, метрики бюджета. "
                    "Использовать при запросах 'рефлексия', 'reflection', 'что делали за X'. "
                    "По умолчанию — последний час."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "period": {
                            "type": "string",
                            "description": (
                                "Период: '1h' (последний час, по умолчанию), "
                                "'today'/'сегодня', '2h', '6h', '24h', 'day', 'week'. "
                                "Формат: '<число>h' или '<число>d'."
                            ),
                        }
                    },
                    "required": [],
                },
            },
            _deep_reflect,
        ),
    ]
