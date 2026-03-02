"""Scrapes vendor pricing pages via Jina Reader (r.jina.ai)."""
import httpx
from app.config import settings


class ScraperError(Exception):
    """Raised when page fetch fails."""


async def fetch_page_markdown(url: str) -> str:
    """Fetch a URL via Jina Reader and return clean Markdown.

    Raises ScraperError on network or HTTP failures.
    """
    jina_url = f"https://r.jina.ai/{url}"
    headers = {
        "Accept": "text/markdown",
        "X-Timeout": "30",
    }
    if settings.jina_api_key:
        headers["Authorization"] = f"Bearer {settings.jina_api_key}"

    try:
        async with httpx.AsyncClient(timeout=float(settings.scraper_timeout)) as client:
            resp = await client.get(jina_url, headers=headers)
            resp.raise_for_status()
            content = resp.text
            if not content or len(content) < 50:
                raise ScraperError(f"Jina returned empty content for {url}")
            return content
    except httpx.TimeoutException:
        raise ScraperError(f"Timed out fetching {url} (>{settings.scraper_timeout}s)")
    except httpx.HTTPStatusError as e:
        raise ScraperError(f"HTTP {e.response.status_code} from Jina for {url}: {e.response.text[:200]}")
    except httpx.RequestError as e:
        raise ScraperError(f"Network error fetching {url}: {e}")
