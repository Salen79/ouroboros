from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.models.user import User
from app.models.analysis import Analysis
from app.auth import get_current_user
from app.services.vendor_analyzer import analyze_vendor
import asyncio

router = APIRouter(prefix="/api/analyses", tags=["analyses"])

class AnalysisRequest(BaseModel):
    vendor_name: str
    vendor_website: Optional[str] = ""
    vendor_description: Optional[str] = ""
    use_case: Optional[str] = ""
    budget_range: Optional[str] = ""
    team_size: Optional[str] = ""
    industry: Optional[str] = ""
    decision_timeline: Optional[str] = ""

async def run_analysis_bg(analysis_id: str, db: AsyncSession):
    """Run analysis in background"""
    try:
        result = await db.execute(select(Analysis).where(Analysis.id == analysis_id))
        analysis = result.scalar_one_or_none()
        if not analysis:
            return
        
        analysis.status = "processing"
        await db.commit()
        
        result_data = await analyze_vendor(analysis)
        
        analysis.status = "completed"
        analysis.report = result_data["report"]
        analysis.clarity_score = result_data["clarity_score"]
        analysis.processing_time_ms = result_data["processing_time_ms"]
        analysis.model_used = result_data["model_used"]
        
        from sqlalchemy.sql import func
        analysis.completed_at = func.now()
        await db.commit()
    except Exception as e:
        try:
            result = await db.execute(select(Analysis).where(Analysis.id == analysis_id))
            analysis = result.scalar_one_or_none()
            if analysis:
                analysis.status = "failed"
                analysis.llm_reasoning = str(e)
                await db.commit()
        except:
            pass

@router.post("/")
async def create_analysis(
    req: AnalysisRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.plan == "free" and current_user.credits_remaining <= 0:
        raise HTTPException(status_code=402, detail="No credits remaining. Upgrade to Pro.")
    
    analysis = Analysis(
        user_id=current_user.id,
        vendor_name=req.vendor_name,
        vendor_website=req.vendor_website,
        vendor_description=req.vendor_description,
        use_case=req.use_case,
        budget_range=req.budget_range,
        team_size=req.team_size,
        industry=req.industry,
        decision_timeline=req.decision_timeline,
        status="pending"
    )
    db.add(analysis)
    
    if current_user.plan == "free":
        current_user.credits_remaining -= 1
    
    await db.commit()
    await db.refresh(analysis)
    
    background_tasks.add_task(run_analysis_bg, str(analysis.id), db)
    
    return {"id": str(analysis.id), "status": "pending"}

@router.get("/")
async def list_analyses(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Analysis)
        .where(Analysis.user_id == current_user.id)
        .order_by(Analysis.created_at.desc())
        .limit(50)
    )
    analyses = result.scalars().all()
    return [
        {
            "id": str(a.id),
            "vendor_name": a.vendor_name,
            "status": a.status,
            "clarity_score": a.clarity_score,
            "verdict": a.report.get("verdict") if a.report else None,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in analyses
    ]

@router.get("/{analysis_id}")
async def get_analysis(
    analysis_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Analysis).where(
            Analysis.id == analysis_id,
            Analysis.user_id == current_user.id
        )
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    return {
        "id": str(analysis.id),
        "vendor_name": analysis.vendor_name,
        "vendor_website": analysis.vendor_website,
        "vendor_description": analysis.vendor_description,
        "use_case": analysis.use_case,
        "budget_range": analysis.budget_range,
        "team_size": analysis.team_size,
        "industry": analysis.industry,
        "status": analysis.status,
        "report": analysis.report,
        "clarity_score": analysis.clarity_score,
        "verdict": analysis.report.get("verdict") if analysis.report else None,
        "processing_time_ms": analysis.processing_time_ms,
        "model_used": analysis.model_used,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
        "completed_at": analysis.completed_at.isoformat() if analysis.completed_at else None,
    }
