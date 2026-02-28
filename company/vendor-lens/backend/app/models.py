"""SQLAlchemy models for VendorLens."""
import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, JSON, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|processing|done|error
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Comparison(Base):
    __tablename__ = "comparisons"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    share_token: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, default=lambda: uuid.uuid4().hex
    )
    analysis_ids: Mapped[list] = mapped_column(JSON, nullable=False)   # list[str]
    table: Mapped[dict | None] = mapped_column(JSON, nullable=True)    # LLM comparison result
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
