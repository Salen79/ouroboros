"""Deep Reflection tool — анализ событий и диалога за указанный период."""

import json
import logging
import os
import pathlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ouroboros.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)

DRIVE_ROOT = os.environ.get("DRIVE_ROOT", os.path.expanduser("~/ouroboros-data"))


def _parse_period(period_str: Optional[str]) -> tuple[datetime, datetime]:
    """Парсит строку периода и возвращает (start, end) в UTC.
    
    Поддерживаемые форматы:
    - None / "" → последний час
    - "1h" / "last_hour" → последний час
    - "today" / "сегодня" → с 00:00 UTC сегодня
    - "2h" → последние 2 часа
    - "24h" / "day" / "день" → последние 24 часа
    - "7d" / "week" → последние 7 дней
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
    
    # Формат "Xh" или "Xd"
    if p.endswith("h") and p[:-1].isdigit():
        hours = int(p[:-1])
        return now - timedelta(hours=hours), now
    
    if p.endswith("d") and p[:-1].isdigit():
        days = int(p[:-1])
        return now - timedelta(days=days), now
    
    # По умолчанию — последний час
    return now - timedelta(hours=1), now


def _read_jsonl_tail(filepath: str, n: int = 500) -> List[dict]:
    """Читает последние n строк JSONL файла."""
    try:
        path = pathlib.Path(filepath)
        if not path.exists():
            return []
        
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        tail_lines = lines[-n:] if len(lines) > n else lines
        
        result = []
        for line in tail_lines:
            line = line.strip()
            if not line:
                continue
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return result
    except Exception as e:
        log.warning("Failed to read %s: %s", filepath, e)
        return []


def _filter_by_period(entries: List[dict], start: datetime, end: datetime, ts_field: str = "ts") -> List[dict]:
    """Фильтрует записи по временному периоду."""
    result = []
    for entry in entries:
        ts_raw = entry.get(ts_field) or entry.get("timestamp") or entry.get("created_at")
        if not ts_raw:
            continue
        try:
            if isinstance(ts_raw, (int, float)):
                ts = datetime.fromtimestamp(ts_raw, tz=timezone.utc)
            else:
                ts_str = str(ts_raw)
                if ts_str.endswith("Z"):
                    ts_str = ts_str[:-1] + "+00:00"
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            
            if start <= ts <= end:
                result.append(entry)
        except (ValueError, TypeError):
            continue
    return result


def _analyze_events(events: List[dict]) -> dict:
    """Анализирует события: задачи, ошибки, инструменты."""
    tasks_done = []
    tasks_failed = []
    tool_counts: Dict[str, int] = {}
    total_cost = 0.0
    rounds_total = 0
    
    for e in events:
        event_type = e.get("type", "")
        
        # Завершённые задачи
        if event_type == "task_complete":
            tasks_done.append({
                "task_id": e.get("task_id", "?"),
                "description": e.get("description", e.get("task_description", ""))[:80],
                "rounds": e.get("rounds", 0),
                "cost_usd": e.get("cost_usd", 0.0),
                "success": e.get("success", True),
            })
            total_cost += e.get("cost_usd", 0.0)
            rounds_total += e.get("rounds", 0)
        
        # Ошибки и MAX_ROUNDS
        elif event_type in ("task_failed", "max_rounds_exceeded", "error"):
            tasks_failed.append({
                "task_id": e.get("task_id", "?"),
                "description": e.get("description", e.get("task_description", ""))[:80],
                "round": e.get("round", e.get("rounds", "?")),
                "cost_usd": e.get("cost_usd", 0.0),
                "reason": e.get("error", e.get("reason", event_type)),
            })
            total_cost += e.get("cost_usd", 0.0)
        
        # Вызовы инструментов
        elif event_type == "tool_call":
            tool_name = e.get("tool_name", e.get("name", "unknown"))
            tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
    
    # Найти циклические паттерны (инструмент вызван 5+ раз)
    circular_suspects = {k: v for k, v in tool_counts.items() if v >= 5}
    top_tools = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    
    return {
        "tasks_done": tasks_done,
        "tasks_failed": tasks_failed,
        "total_cost": total_cost,
        "rounds_total": rounds_total,
        "top_tools": top_tools,
        "circular_suspects": circular_suspects,
    }


def _analyze_chat(chat_entries: List[dict]) -> dict:
    """Анализирует диалог: темы, запросы Sergey, длина."""
    user_messages = []
    agent_messages = []
    
    for entry in chat_entries:
        role = entry.get("role", "")
        content = entry.get("content", "") or entry.get("text", "")
        
        if role == "user":
            user_messages.append(str(content)[:200])
        elif role == "assistant":
            agent_messages.append(str(content)[:200])
    
    return {
        "user_count": len(user_messages),
        "agent_count": len(agent_messages),
        "user_messages": user_messages[:10],  # последние 10
    }


def _assess_constitution(events: List[dict], chat: List[dict]) -> List[str]:
    """Честная оценка соответствия конституции."""
    issues = []
    
    # P8: бюджет
    costs = [e.get("cost_usd", 0) for e in events if e.get("cost_usd", 0) > 2.0]
    if costs:
        issues.append(f"P8: Обнаружены дорогие задачи (>{2}$): {len(costs)} шт.")
    
    # MAX_ROUNDS
    max_rounds = [e for e in events if e.get("type") == "max_rounds_exceeded"]
    if max_rounds:
        issues.append(f"P15: {len(max_rounds)} задач превысили MAX_ROUNDS — circular loop?")
    
    # Английский в сообщениях агента
    english_drift = 0
    for entry in chat:
        if entry.get("role") == "assistant":
            content = str(entry.get("content", ""))
            # Грубая эвристика: если много английских слов в ряд
            words = content.split()[:30]
            eng_words = sum(1 for w in words if w.isalpha() and all(ord(c) < 128 for c in w))
            if eng_words > 15:  # больше 15 чисто английских слов из первых 30
                english_drift += 1
    
    if english_drift > 0:
        issues.append(f"P21: Возможный language drift — {english_drift} сообщений с английским текстом")
    
    return issues if issues else ["Нарушений не обнаружено"]


def _deep_reflect(ctx: ToolContext, period: str = "", **kwargs) -> str:
    """Выполняет глубокую рефлексию за указанный период."""
    
    drive_root = pathlib.Path(ctx.drive_root if hasattr(ctx, "drive_root") and ctx.drive_root else DRIVE_ROOT)
    
    # Шаг 0: определить период
    period_start, period_end = _parse_period(period)
    period_label = (
        f"{period_start.strftime('%Y-%m-%d %H:%M')} — {period_end.strftime('%H:%M')} UTC"
    )
    
    # Шаг 1: сбор данных
    events_path = str(drive_root / "logs" / "events.jsonl")
    chat_path = str(drive_root / "logs" / "chat.jsonl")
    state_path = str(drive_root / "state" / "state.json")
    
    all_events = _read_jsonl_tail(events_path, 500)
    all_chat = _read_jsonl_tail(chat_path, 200)
    
    # Шаг 2: фильтрация по периоду
    period_events = _filter_by_period(all_events, period_start, period_end)
    period_chat = _filter_by_period(all_chat, period_start, period_end)
    
    # Если фильтрация дала 0 результатов — взять последние N записей как fallback
    if not period_events and all_events:
        period_events = all_events[-50:]
        period_label += " (fallback: последние 50 событий)"
    if not period_chat and all_chat:
        period_chat = all_chat[-20:]
    
    # Шаг 3-5: анализ
    event_analysis = _analyze_events(period_events)
    chat_analysis = _analyze_chat(period_chat)
    constitution_issues = _assess_constitution(period_events, period_chat)
    
    # Шаг 7: бюджет из state.json
    budget_info = ""
    try:
        state = json.loads(pathlib.Path(state_path).read_text())
        spent = state.get("spent_usd", 0)
        total = state.get("total_usd", 500)
        remaining = total - spent
        period_cost = event_analysis["total_cost"]
        budget_info = f"-${period_cost:.3f} за период / остаток ${remaining:.2f}"
    except Exception:
        budget_info = "данные недоступны"
    
    # Шаг 9: форматирование
    lines = [f"🔍 РЕФЛЕКСИЯ {period_label}", ""]
    
    # Сделано
    done = event_analysis["tasks_done"]
    total_cost = event_analysis["total_cost"]
    lines.append(f"✅ СДЕЛАНО ({len(done)} задач, ~${total_cost:.3f} потрачено)")
    if done:
        for t in done[:10]:
            status = "✅" if t["success"] else "⚠️"
            lines.append(f"• {t['task_id'][:12]}: {t['description']} | {t['rounds']}r / ${t['cost_usd']:.3f} / {status}")
    else:
        lines.append("• Завершённых задач не найдено в период")
    lines.append("")
    
    # Не получилось
    failed = event_analysis["tasks_failed"]
    lines.append(f"❌ НЕ ПОЛУЧИЛОСЬ ({len(failed)})")
    if failed:
        for t in failed[:5]:
            lines.append(f"• {t['task_id'][:12]}: раунд {t['round']} — {str(t['reason'])[:60]} / ${t['cost_usd']:.3f}")
    else:
        lines.append("• Провалов не найдено")
    lines.append("")
    
    # Конституция
    lines.append("⚖️ КОНСТИТУЦИЯ (P0-P20)")
    for issue in constitution_issues:
        lines.append(f"• {issue}")
    lines.append("")
    
    # Узкие места
    lines.append("🔧 УЗКИЕ МЕСТА")
    circular = event_analysis["circular_suspects"]
    if circular:
        for tool, count in sorted(circular.items(), key=lambda x: x[1], reverse=True)[:5]:
            lines.append(f"• {tool}: вызван {count}x — возможный loop")
    else:
        top = event_analysis["top_tools"]
        if top:
            for tool, count in top[:5]:
                lines.append(f"• {tool}: {count}x")
        else:
            lines.append("• Данные по инструментам отсутствуют")
    lines.append("")
    
    # Дельта состояния
    lines.append("📊 ДЕЛЬТА СОСТОЯНИЯ")
    lines.append(f"• Бюджет: {budget_info}")
    lines.append(f"• Диалог: {chat_analysis['user_count']} сообщений от Sergey, {chat_analysis['agent_count']} от THAI")
    lines.append(f"• Событий за период: {len(period_events)}")
    lines.append("")
    
    # Топ-3 действия
    lines.append("🎯 ТОП-3 ДЕЙСТВИЯ")
    actions = _generate_actions(event_analysis, constitution_issues)
    for i, action in enumerate(actions[:3], 1):
        lines.append(f"{i}. {action}")
    
    return "\n".join(lines)


def _generate_actions(analysis: dict, constitution_issues: List[str]) -> List[str]:
    """Генерирует конкретные действия на основе анализа."""
    actions = []
    
    # Если были MAX_ROUNDS
    failed = analysis["tasks_failed"]
    max_rounds_failures = [t for t in failed if "max_rounds" in str(t.get("reason", "")).lower()]
    if max_rounds_failures:
        actions.append(
            f"Декомпозировать задачу '{max_rounds_failures[0]['description'][:40]}' "
            f"→ снизить количество MAX_ROUNDS failures с {len(max_rounds_failures)} до 0"
        )
    
    # Если есть circular loop кандидаты
    circular = analysis["circular_suspects"]
    if circular:
        top_circular = sorted(circular.items(), key=lambda x: x[1], reverse=True)[0]
        actions.append(
            f"Расследовать повторный вызов {top_circular[0]} ({top_circular[1]}x) "
            f"→ добавить кэш или guard condition"
        )
    
    # Конституционные нарушения
    real_issues = [i for i in constitution_issues if "нарушений" not in i.lower()]
    if real_issues:
        actions.append(
            f"Устранить: {real_issues[0][:80]} → привести в соответствие с конституцией"
        )
    
    # Если действий меньше 3 — добавить дефолтные
    if len(actions) < 3:
        if analysis["tasks_done"]:
            actions.append("Обновить knowledge base по завершённым задачам → накопить институциональные знания")
        actions.append("Запустить run_ops_check → убедиться что production сервисы здоровы")
        actions.append("Обновить identity.md → отразить рефлексию текущего периода")
    
    return actions[:3]


def get_tools():
    return [
        ToolEntry("deep_reflection", {
            "name": "deep_reflection",
            "description": (
                "Выполняет глубокую рефлексию за указанный период: "
                "собирает данные из events.jsonl и chat.jsonl, анализирует выполненные задачи, "
                "ошибки, узкие места, конституционное соответствие, дельту бюджета. "
                "Возвращает структурированный отчёт. "
                "По умолчанию — последний час. "
                "Использовать при запросах 'рефлексия', 'reflection', 'что мы делали за X'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "description": (
                            "Период для анализа. Примеры: '1h' (последний час, по умолчанию), "
                            "'today' / 'сегодня', '2h', '24h', 'day', 'week'. "
                            "Если не указан — анализируется последний час."
                        ),
                    }
                },
                "required": [],
            },
        }, _deep_reflect),
    ]
