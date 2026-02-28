"""Side-by-side comparison of multiple analyses."""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Analysis

router = APIRouter(prefix="/api/compare", tags=["compare"])


class CompareRequest(BaseModel):
    analysis_ids: List[str]


@router.post("")
async def compare_analyses(
    req: CompareRequest,
    db: AsyncSession = Depends(get_db),
):
    """Return multiple analyses side-by-side for comparison."""
    if len(req.analysis_ids) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 analyses to compare")
    if len(req.analysis_ids) > 5:
        raise HTTPException(status_code=400, detail="Maximum 5 analyses per comparison")

    results = []
    for aid in req.analysis_ids:
        obj = await db.get(Analysis, aid)
        if not obj:
            raise HTTPException(status_code=404, detail=f"Analysis {aid} not found")
        if obj.status != "done":
            raise HTTPException(status_code=400, detail=f"Analysis {aid} is not complete yet (status: {obj.status})")
        results.append({"id": obj.id, "url": obj.url, "result": obj.result})

    return {"analyses": results, "count": len(results)}
