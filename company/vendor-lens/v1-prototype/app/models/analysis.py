from sqlalchemy import Column, String, DateTime, Integer, Text, Float, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.database import Base
import uuid

class Analysis(Base):
    __tablename__ = "analyses"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    
    # Input
    vendor_name = Column(String(255), nullable=False)
    vendor_website = Column(String(500), default="")
    vendor_description = Column(Text, default="")
    use_case = Column(Text, default="")
    budget_range = Column(String(100), default="")
    team_size = Column(String(100), default="")
    industry = Column(String(100), default="")
    decision_timeline = Column(String(100), default="")
    
    # Output
    status = Column(String(50), default="pending")  # pending, processing, completed, failed
    report = Column(JSONB, nullable=True)
    clarity_score = Column(Float, nullable=True)
    processing_time_ms = Column(Integer, nullable=True)
    model_used = Column(String(50), default="gpt-4o")
    llm_reasoning = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
