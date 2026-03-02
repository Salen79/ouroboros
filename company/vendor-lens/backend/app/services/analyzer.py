"""LLM-powered analysis of vendor pricing pages."""
import json
from openai import AsyncOpenAI, RateLimitError, APITimeoutError, APIError
from app.config import settings

_client = None


class AnalyzerError(Exception):
    """Raised when LLM analysis fails."""
    pass


def get_llm_client() -> AsyncOpenAI:
    global _client
    if _client is None:
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
}"""


async def analyze_vendor(url: str, page_markdown: str) -> dict:
    """Send page content to LLM and return structured analysis."""
    client = get_llm_client()
    content = page_markdown[:15000]

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
        raise AnalyzerError(f"Rate limit exceeded: {e}") from e
    except APITimeoutError as e:
        raise AnalyzerError(f"LLM request timed out: {e}") from e
    except APIError as e:
        raise AnalyzerError(f"LLM API error: {e}") from e

    raw = response.choices[0].message.content
    if not raw:
        raise AnalyzerError("LLM returned empty response")

    if raw.strip().startswith("```"):
        raw = raw.strip().lstrip("`json").lstrip("`").rstrip("`").strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise AnalyzerError(f"Failed to parse LLM response as JSON: {e}") from e
