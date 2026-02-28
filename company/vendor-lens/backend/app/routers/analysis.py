"""Analysis endpoints: submit URL, poll status, get result, export."""
from uuid import uuid4
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import asyncio

from app.database import get_db
from app.models import Analysis
from app.services.scraper import fetch_page_markdown
from app.services.analyzer import analyze_vendor

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


@router.post("", response_model=SubmitResponse, status_code=202)
async def submit_analysis(
    req: SubmitRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Queue a URL for analysis."""
    url_str = str(req.url)
    analysis = Analysis(
        id=str(uuid4()),
        url=url_str,
        status="pending",
        client_ip=request.client.host if request.client else None,
    )
    db.add(analysis)
    await db.commit()
    await db.refresh(analysis)

    background_tasks.add_task(_run_analysis, analysis.id, url_str)
    return SubmitResponse(id=analysis.id, status=analysis.status)


@router.get("/{analysis_id}")
async def get_analysis(analysis_id: str, db: AsyncSession = Depends(get_db)):
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
        "created_at": obj.created_at,
    }
