"""Scrapes vendor pricing pages via Jina Reader (r.jina.ai)."""
import httpx
from app.config import settings


async def fetch_page_markdown(url: str) -> str:
    """Fetch a URL and return its content as clean Markdown via Jina Reader."""
    jina_url = f"https://r.jina.ai/{url}"
    headers = {
        "Accept": "text/markdown",
        "X-Timeout": "30",
    }
    if settings.jina_api_key:
        headers["Authorization"] = f"Bearer {settings.jina_api_key}"

    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.get(jina_url, headers=headers)
        resp.raise_for_status()
        return resp.text
