"""Side-by-side comparison of multiple analyses."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Analysis, Comparison
from app.schemas import ComparisonCreateRequest, ComparisonResponse
from app.services.comparator import compare_analyses

router = APIRouter(prefix="/api/comparisons", tags=["comparisons"])


async def _run_comparison(comparison_id: str, analysis_ids: list[str]) -> None:
    """Background: load analyses → LLM compare → store result."""
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        comp = await db.get(Comparison, comparison_id)
        if not comp:
            return
        try:
            analyses = []
            for aid in analysis_ids:
                obj = await db.get(Analysis, aid)
                if obj and obj.result:
                    analyses.append(obj.result)

            if len(analyses) < 2:
                comp.table = {"error": "Not enough completed analyses to compare"}
            else:
                comp.table = await compare_analyses(analyses)

            await db.commit()
        except Exception as exc:
            comp.table = {"error": str(exc)}
            await db.commit()


@router.post("", response_model=ComparisonResponse, status_code=202)
async def create_comparison(
    req: ComparisonCreateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Create a comparison between 2–3 vendor analyses."""
    if not (2 <= len(req.analysis_ids) <= 3):
        raise HTTPException(status_code=400, detail="Provide between 2 and 3 analysis IDs")

    comp = Comparison(analysis_ids=req.analysis_ids)
    db.add(comp)
    await db.commit()
    await db.refresh(comp)

    background_tasks.add_task(_run_comparison, comp.id, req.analysis_ids)

    return ComparisonResponse(
        id=comp.id,
        share_token=comp.share_token,
        analysis_ids=comp.analysis_ids,
        table=comp.table,
        created_at=comp.created_at,
    )


@router.get("/{comparison_id}", response_model=ComparisonResponse)
async def get_comparison(comparison_id: str, db: AsyncSession = Depends(get_db)):
    """Poll or retrieve a comparison result."""
    comp = await db.get(Comparison, comparison_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Comparison not found")
    return ComparisonResponse(
        id=comp.id,
        share_token=comp.share_token,
        analysis_ids=comp.analysis_ids,
        table=comp.table,
        created_at=comp.created_at,
    )


@router.get("/share/{token}", response_model=ComparisonResponse)
async def get_comparison_by_share_token(token: str, db: AsyncSession = Depends(get_db)):
    """Retrieve a comparison by its public share token."""
    result = await db.execute(select(Comparison).where(Comparison.share_token == token))
    comp = result.scalar_one_or_none()
    if not comp:
        raise HTTPException(status_code=404, detail="Comparison not found")
    return ComparisonResponse(
        id=comp.id,
        share_token=comp.share_token,
        analysis_ids=comp.analysis_ids,
        table=comp.table,
        created_at=comp.created_at,
    )
