"""Scrapes vendor pricing pages via Jina Reader (r.jina.ai)."""
import httpx
from app.config import settings


class ScraperError(Exception):
    """Raised when scraping fails."""
    pass


async def scrape_url(url: str) -> str:
    """Fetch URL and return Markdown content via Jina Reader."""
    return await fetch_page_markdown(url)


async def fetch_page_markdown(url: str) -> str:
    """Fetch a URL and return its content as clean Markdown via Jina Reader."""
    jina_url = f"https://r.jina.ai/{url}"
    headers = {
        "Accept": "text/markdown",
        "X-Timeout": "30",
    }
    if settings.jina_api_key:
        headers["Authorization"] = f"Bearer {settings.jina_api_key}"

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.get(jina_url, headers=headers)
            resp.raise_for_status()
            content = resp.text
    except httpx.TimeoutException as e:
        raise ScraperError(f"Scraping timed out for {url}") from e
    except httpx.HTTPStatusError as e:
        raise ScraperError(f"HTTP {e.response.status_code} for {url}") from e
    except httpx.RequestError as e:
        raise ScraperError(f"Network error scraping {url}: {e}") from e

    if not content or len(content.strip()) < 100:
        raise ScraperError(f"Empty or too-short content from {url}")

    return content
