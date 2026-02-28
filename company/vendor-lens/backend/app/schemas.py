"""Pydantic schemas for VendorLens API."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, HttpUrl


# ── Analysis ──────────────────────────────────────────────────────────────────

class AnalysisSubmitRequest(BaseModel):
    url: HttpUrl


class AnalysisSubmitResponse(BaseModel):
    id: str
    status: str


class AnalysisResult(BaseModel):
    id: str
    url: str
    status: str          # pending | processing | done | error
    result: dict | None = None
    error: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


# ── Comparison ────────────────────────────────────────────────────────────────

class ComparisonCreateRequest(BaseModel):
    analysis_ids: list[str]   # 2–3 IDs


class ComparisonResponse(BaseModel):
    id: str
    share_token: str
    analysis_ids: list[str]
    table: dict | None = None   # structured side-by-side table
    created_at: datetime

    class Config:
        from_attributes = True
