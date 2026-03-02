"""Analysis endpoints: submit URL, poll status, get result, list recent."""
from urllib.parse import urlparse, urlunparse
from uuid import uuid4
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, text
from slowapi import Limiter
from slowapi.util import get_remote_address as _get_remote_address

from app.database import get_db
from app.models import Analysis
from app.services.scraper import fetch_page_markdown
from app.services.analyzer import analyze_vendor
from app.security import validate_url


def get_client_ip(request: Request) -> str:
    """Get real client IP, preferring CF-Connecting-IP when behind Cloudflare."""
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return _get_remote_address(request)


def normalize_url(url: str) -> str:
    """Normalize URL for consistent deduplication.

    - Lowercases scheme and host
    - Strips trailing slash from path (unless path is just '/')
    - Removes default ports (80 for http, 443 for https)
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    # Remove default ports
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    elif netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]
    path = parsed.path.rstrip("/") or "/"
    # Reconstruct without fragment
    normalized = urlunparse((scheme, netloc, path, parsed.params, parsed.query, ""))
    return normalized


limiter = Limiter(key_func=get_client_ip)

router = APIRouter(prefix="/api/analyses", tags=["analyses"])


class SubmitRequest(BaseModel):
    url: HttpUrl


class SubmitResponse(BaseModel):
    id: str
    status: str


async def _run_analysis(analysis_id: str, url: str) -> None:
    """Background task: scrape + analyze, update DB."""
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        obj = await db.get(Analysis, analysis_id)
        if not obj:
            return
        try:
            obj.status = "processing"
            await db.commit()

            markdown = await fetch_page_markdown(url)
            result = await analyze_vendor(url, markdown)

            obj.result = result
            obj.status = "done"
        except Exception as exc:
            obj.status = "error"
            obj.error = str(exc)
        await db.commit()


@router.get("")
@limiter.limit("60/minute")
async def list_analyses(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List recent completed analyses, deduplicated by URL (latest per URL)."""
    # DISTINCT ON url: one row per URL, the most recent one
    result = await db.execute(
        text("""
            SELECT id, url, status, result, created_at
            FROM (
                SELECT DISTINCT ON (url) id, url, status, result, created_at
                FROM analyses
                WHERE status = 'done'
                ORDER BY url, created_at DESC
            ) deduped
            ORDER BY created_at DESC
            LIMIT :limit
        """),
        {"limit": limit},
    )
    rows = result.mappings().all()
    return [
        {
            "id": r["id"],
            "url": r["url"],
            "status": r["status"],
            "result": r["result"],
            "created_at": str(r["created_at"]),
        }
        for r in rows
    ]


@router.post("", response_model=SubmitResponse, status_code=202)
@limiter.limit("5/minute;20/hour")
async def submit_analysis(
    req: SubmitRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Queue a URL for analysis. Returns cached result if URL was analyzed before."""
    url_str = normalize_url(str(req.url))

    # Security: validate URL (SSRF prevention)
    validate_url(url_str)

    # Check cache: already analyzed this URL? Return existing result.
    existing = await db.execute(
        select(Analysis)
        .where(Analysis.url == url_str, Analysis.status == "done")
        .order_by(desc(Analysis.created_at))
        .limit(1)
    )
    cached = existing.scalars().first()
    if cached:
        return SubmitResponse(id=cached.id, status=cached.status)

    # Also check if analysis is already in progress for this URL
    in_progress = await db.execute(
        select(Analysis)
        .where(Analysis.url == url_str, Analysis.status.in_(["pending", "processing"]))
        .order_by(desc(Analysis.created_at))
        .limit(1)
    )
    running = in_progress.scalars().first()
    if running:
        return SubmitResponse(id=running.id, status=running.status)

    analysis = Analysis(
        id=str(uuid4()),
        url=url_str,
        status="pending",
    )
    db.add(analysis)
    await db.commit()
    await db.refresh(analysis)

    background_tasks.add_task(_run_analysis, analysis.id, url_str)
    return SubmitResponse(id=analysis.id, status=analysis.status)


@router.get("/{analysis_id}")
@limiter.limit("120/minute")
async def get_analysis(
    request: Request,
    analysis_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Poll status or get full result."""
    obj = await db.get(Analysis, analysis_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return {
        "id": obj.id,
        "url": obj.url,
        "status": obj.status,
        "result": obj.result,
        "error": obj.error,
        "created_at": str(obj.created_at),
    }
