"""Cross-model LLM-as-judge.

Per O3: Sonnet + GPT-4.1, both via OpenRouter. Per scenario, each model
runs N times (default 1). Verdicts aggregated into a consensus per the
table in the design spec.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Tuple

log = logging.getLogger(__name__)

JUDGE_TIMEOUT_SEC = 60.0
DEFAULT_RUNS_PER_MODEL = 1


def _build_prompt(scenario_title: str, covers: List[str], task_text: str,
                  final_text: str, events: List[Dict[str, Any]],
                  tool_calls: List[Dict[str, Any]],
                  criteria: str) -> str:
    events_summary = "\n".join(
        f"- {e.get('type')}: {json.dumps({k: v for k, v in e.items() if k in ('type','args','reason','tool','name')}, default=str)[:200]}"
        for e in events[:50]
    )
    tools_summary = "\n".join(
        f"- {t.get('tool') or t.get('name')}: args={json.dumps(t.get('args', {}), default=str)[:200]}"
        for t in tool_calls[:30]
    )
    return f"""## Scenario
{scenario_title}
Covers Dark Zones: {', '.join(covers)}

## Task input
{task_text}

## Agent final output
{final_text or '(empty)'}

## Events emitted (first 50)
{events_summary or '(none)'}

## Tool calls (first 30)
{tools_summary or '(none)'}

## Criteria
{criteria}

Return JSON only, no prose:
{{"verdict": "pass" | "fail" | "inconclusive",
  "rationale": "concise reasoning, < 300 chars",
  "specific_failures": ["...", "..."]}}
"""


def _call_openrouter(model: str, prompt: str) -> Tuple[Dict[str, Any], float]:
    """Call OpenRouter chat/completions; return (parsed_json, spend_usd_estimate).

    Estimate spend via token count when OpenRouter doesn't return cost
    in the response (we don't fetch the generation API for the judge —
    cheaper to estimate)."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    import httpx
    payload = {
        "model": model,
        "messages": [
            {"role": "system",
             "content": "You are a strict evaluation judge. Output JSON only."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 600,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/Salen79/ouroboros",
        "X-Title": "Ouroboros-Eval",
    }
    with httpx.Client(timeout=JUDGE_TIMEOUT_SEC) as client:
        resp = client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload, headers=headers,
        )
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    pt = int(usage.get("prompt_tokens", 0))
    ct = int(usage.get("completion_tokens", 0))
    # Rough per-token estimates; refined post-baseline.
    rate_in, rate_out = _model_rates(model)
    spend = (pt / 1_000_000) * rate_in + (ct / 1_000_000) * rate_out

    parsed = _extract_json(text)
    parsed["_raw"] = text
    parsed["_prompt_tokens"] = pt
    parsed["_completion_tokens"] = ct
    return parsed, spend


def _model_rates(model: str) -> Tuple[float, float]:
    """Approximate per-million-token input/output rates in USD."""
    if "claude-sonnet" in model:
        return 3.0, 15.0
    if "gpt-4.1" in model:
        return 2.0, 8.0
    return 5.0, 15.0


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> Dict[str, Any]:
    """Strict parse, with one fenced-block fallback."""
    try:
        return json.loads(text)
    except Exception:
        pass
    m = _JSON_BLOCK.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return {"verdict": "inconclusive", "rationale": "judge returned non-JSON",
            "specific_failures": ["parse_error"]}


def _normalize_verdict(v: Any) -> str:
    s = str(v).strip().lower()
    if s in ("pass", "fail", "inconclusive"):
        return s
    return "inconclusive"


def _consensus(verdicts: List[str]) -> Tuple[str, str]:
    """Apply the design-spec consensus table.

    Returns (consensus_verdict, reason).
    """
    counts = {v: verdicts.count(v) for v in ("pass", "fail", "inconclusive")}
    distinct = {v for v in verdicts if v in ("pass", "fail")}
    if counts["fail"] > 0 and counts["pass"] == 0:
        return "fail", "all_non_pass_at_least_one_fail"
    if counts["pass"] > 0 and counts["fail"] == 0 and counts["inconclusive"] == 0:
        return "pass", "all_judges_pass"
    if counts["pass"] > 0 and counts["fail"] > 0:
        return "inconclusive", "judge_disagreement"
    if counts["pass"] > 0 and counts["inconclusive"] > 0 and counts["fail"] == 0:
        return "inconclusive", "judge_low_confidence"
    if counts["fail"] > 0 and counts["inconclusive"] > 0:
        return "fail", "fail_dominates_inconclusive"
    return "inconclusive", "no_judges_or_all_inconclusive"


def run_judges(
    scenario_title: str,
    covers: List[str],
    task_text: str,
    final_text: str,
    events: List[Dict[str, Any]],
    tool_calls: List[Dict[str, Any]],
    criteria: str,
    models: List[str],
    runs_per_model: int,
    judge_under_cap: callable,
    record_spend: callable,
) -> Dict[str, Any]:
    """Returns dict with judge_calls list, consensus, and reason."""
    prompt = _build_prompt(scenario_title, covers, task_text, final_text,
                           events, tool_calls, criteria)
    judge_calls = []
    truncated = False
    for model in models:
        for i in range(runs_per_model):
            if not judge_under_cap():
                truncated = True
                break
            try:
                parsed, spend = _call_openrouter(model, prompt)
                verdict = _normalize_verdict(parsed.get("verdict"))
                judge_calls.append({
                    "model": model,
                    "call_index": i,
                    "verdict": verdict,
                    "rationale": parsed.get("rationale", ""),
                    "specific_failures": parsed.get("specific_failures", []),
                    "raw_response": parsed.get("_raw", ""),
                    "prompt_tokens": parsed.get("_prompt_tokens", 0),
                    "completion_tokens": parsed.get("_completion_tokens", 0),
                    "spend_usd": round(spend, 6),
                })
                record_spend(model, "judge", parsed.get("_prompt_tokens", 0),
                             parsed.get("_completion_tokens", 0), spend)
            except Exception as e:
                judge_calls.append({
                    "model": model,
                    "call_index": i,
                    "verdict": "inconclusive",
                    "rationale": f"judge_error: {type(e).__name__}: {e}",
                    "specific_failures": ["judge_error"],
                    "raw_response": "",
                    "spend_usd": 0.0,
                    "error": True,
                })
        if truncated:
            break

    verdicts = [c["verdict"] for c in judge_calls]
    consensus, reason = _consensus(verdicts)
    return {
        "judge_calls": judge_calls,
        "consensus": consensus,
        "consensus_reason": reason,
        "judge_truncated": truncated,
    }
