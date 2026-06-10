from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


class CaseRecord(Base):
    __tablename__ = "cases"

    case_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    case_name: Mapped[str] = mapped_column(String(255), nullable=False)
    drawing_parse_result_json: Mapped[str] = mapped_column(Text, nullable=False)
    process_plan_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_files_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    external_conditions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation_ai_response_json: Mapped[str | None] = mapped_column(LONGTEXT().with_variant(Text, "sqlite"), nullable=True)
    human_edits_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    ai_errors_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="draft")
    quality: Mapped[str | None] = mapped_column(String(64), nullable=True)
    creator: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    review_comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    production_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_duration: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quality_issues_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class CaseAnnotationJobRecord(Base):
    __tablename__ = "case_annotation_jobs"

    job_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    stage: Mapped[str] = mapped_column(String(64), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="等待开始精细标注")
    ai_stream_preview: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ai_stream_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class CaseAnnotationResultRecord(Base):
    __tablename__ = "case_annotation_results"

    case_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(128), nullable=False)
    explanations_json: Mapped[str] = mapped_column(LONGTEXT().with_variant(Text, "sqlite"), nullable=False)
    export_csv_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def init_db() -> None:
    try:
        Base.metadata.create_all(bind=engine)
        if engine.dialect.name == "mysql":
            with engine.begin() as connection:
                columns = {column["name"] for column in inspect(connection).get_columns("cases")}
                if "generation_ai_response_json" not in columns:
                    connection.execute(
                        text(
                            "ALTER TABLE cases "
                            "ADD COLUMN generation_ai_response_json LONGTEXT NULL "
                            "AFTER external_conditions_json"
                        )
                    )
                else:
                    connection.execute(
                        text(
                            "ALTER TABLE cases "
                            "MODIFY generation_ai_response_json LONGTEXT NULL"
                        )
                    )
                connection.execute(
                    text(
                        "ALTER TABLE case_annotation_results "
                        "MODIFY explanations_json LONGTEXT NOT NULL"
                    )
                )
    except SQLAlchemyError as exc:
        print(f"[db] mysql init failed: {type(exc).__name__}: {exc}", flush=True)
