"""Side-by-side comparison of multiple vendor analyses via LLM."""
import json
from openai import AsyncOpenAI
from app.config import settings
from app.services.analyzer import get_llm_client

COMPARE_SYSTEM = """You are VendorLens Comparator. You receive 2-3 vendor analysis JSONs.
Return ONLY valid JSON:
{
  "summary": "1-2 sentence comparison overview",
  "winner": "vendor name or null if inconclusive",
  "winner_reason": "string",
  "table": {
    "rows": [
      {
        "label": "string",
        "values": ["value for vendor 1", "value for vendor 2"]
      }
    ],
    "vendors": ["Vendor A", "Vendor B"]
  },
  "risk_comparison": [
    {"vendor": "string", "risk_level": "high|medium|low", "top_risk": "string"}
  ],
  "recommendation": "string"
}"""


async def compare_analyses(analyses: list[dict]) -> dict:
    """LLM-powered side-by-side comparison of 2-3 vendor analyses."""
    client = get_llm_client()

    payload = json.dumps(analyses, indent=2)[:20000]  # stay within context

    response = await client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": COMPARE_SYSTEM},
            {"role": "user", "content": f"Compare these vendor analyses:\n\n{payload}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )

    raw = response.choices[0].message.content
    return json.loads(raw)
