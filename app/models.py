from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Float, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Story(Base):
    __tablename__ = "stories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(1200), nullable=False)
    source_name: Mapped[str] = mapped_column(String(150), nullable=False)
    source_domain: Mapped[str] = mapped_column(String(150), nullable=False)

    sector: Mapped[str] = mapped_column(String(80), nullable=False)
    subtopic: Mapped[str] = mapped_column(String(120), nullable=False)

    summary: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)

    score: Mapped[float] = mapped_column(Float, nullable=False)
    heat_score: Mapped[float] = mapped_column(Float, nullable=False)
    run_type: Mapped[str] = mapped_column(String(30), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("url", "snapshot_date", name="uq_story_url_snapshot"),
        Index("ix_story_sector_snapshot_score", "sector", "snapshot_date", "score"),
        Index("ix_story_snapshot_score", "snapshot_date", "score"),
        Index("ix_story_fingerprint_snapshot", "fingerprint", "snapshot_date"),
    )


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_type: Mapped[str] = mapped_column(String(30), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    message: Mapped[str] = mapped_column(String(500), default="", nullable=False)
