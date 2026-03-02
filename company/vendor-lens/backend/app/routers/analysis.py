"""Analysis endpoints: submit URL, poll status, get result, list recent."""
from uuid import uuid4
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.database import get_db
from app.models import Analysis
from app.services.scraper import fetch_page_markdown
from app.services.analyzer import analyze_vendor
from app.security import validate_url

limiter = Limiter(key_func=get_remote_address)

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
    """List recent completed analyses."""
    result = await db.execute(
        select(Analysis)
        .where(Analysis.status == "done")
        .order_by(desc(Analysis.created_at))
        .limit(limit)
    )
    rows = result.scalars().all()
    return [
        {
            "id": r.id,
            "url": r.url,
            "status": r.status,
            "result": r.result,
            "created_at": str(r.created_at),
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
    """Queue a URL for analysis. Rate limited: 5/min, 20/hour per IP."""
    url_str = str(req.url)

    # Security: validate URL (SSRF prevention)
    validate_url(url_str)

    # Check cache: already analyzed this URL recently
    existing = await db.execute(
        select(Analysis)
        .where(Analysis.url == url_str, Analysis.status == "done")
        .order_by(desc(Analysis.created_at))
        .limit(1)
    )
    cached = existing.scalars().first()
    if cached:
        return SubmitResponse(id=cached.id, status=cached.status)

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
