"""LLM-powered analysis of vendor pricing pages."""
import json
import logging
from openai import AsyncOpenAI, APIError, APITimeoutError, RateLimitError
from app.config import settings

logger = logging.getLogger(__name__)

_client = None


def get_llm_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set. Cannot run LLM analysis.")
        _client = AsyncOpenAI(
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
        )
    return _client


SYSTEM_PROMPT = """You are VendorLens — a pricing intelligence assistant for indie developers and small teams.
Analyze the provided vendor pricing page content and extract structured data.

Return ONLY valid JSON matching this exact schema:
{
  "vendor_name": "string",
  "summary": "2-3 sentence plain-English summary of what this tool does and who it's for",
  "plans": [
    {
      "name": "string",
      "price_usd_monthly": number or null,
      "price_usd_annual": number or null,
      "is_free_tier": boolean,
      "key_features": ["string"],
      "limits": {"key": "value"}
    }
  ],
  "free_tier": boolean,
  "open_source": boolean,
  "self_hostable": boolean,
  "risks": [
    {
      "level": "high|medium|low",
      "description": "string"
    }
  ],
  "alternatives": ["string"],
  "best_for": "indie|small_team|enterprise|all",
  "verdict": "string (1 sentence recommendation)"
}

Important: respond with ONLY the JSON object, no markdown fences or extra text."""


class AnalyzerError(Exception):
    """Raised when LLM analysis fails."""


async def analyze_vendor(url: str, page_markdown: str) -> dict:
    """Send page content to LLM and return structured analysis.

    Raises AnalyzerError on LLM or parse failures.
    """
    client = get_llm_client()

    # Truncate to stay within context limits
    content = page_markdown[: settings.llm_max_content_chars]
    if len(page_markdown) > settings.llm_max_content_chars:
        logger.info(
            "Content truncated from %d to %d chars for %s",
            len(page_markdown),
            settings.llm_max_content_chars,
            url,
        )

    try:
        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Analyze this vendor pricing page for {url}:\n\n{content}",
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
    except RateLimitError as e:
        raise AnalyzerError(f"LLM rate limit hit: {e}") from e
    except APITimeoutError as e:
        raise AnalyzerError(f"LLM request timed out: {e}") from e
    except APIError as e:
        raise AnalyzerError(f"LLM API error ({e.status_code}): {e.message}") from e

    raw = response.choices[0].message.content
    if not raw:
        raise AnalyzerError("LLM returned empty response")

    # Strip accidental markdown fences
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("LLM returned invalid JSON for %s: %s", url, raw[:500])
        raise AnalyzerError(f"LLM returned invalid JSON: {e}") from e
