"""Log entry model and Pydantic schemas."""

from datetime import datetime, timezone

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LogEntryBase(SQLModel):
    task_name: str = Field(index=True, max_length=128)
    level: str = Field(default="INFO", max_length=16)
    timestamp: datetime = Field(default_factory=_utcnow, index=True)
    message: str
    source_host: str | None = Field(default=None, max_length=128)


class LogEntry(LogEntryBase, table=True):
    __tablename__ = "log_entries"
    __table_args__ = (Index("ix_log_entries_task_id", "task_name", "id"),)

    id: int | None = Field(default=None, primary_key=True)


class LogEntryCreate(SQLModel):
    """Payload accepted by ``POST /api/log``."""

    task: str
    level: str = "INFO"
    message: str
    timestamp: datetime | None = None
    host: str | None = None


class LogEntryRead(SQLModel):
    """Per-row response returned to clients and templates."""

    id: int
    task_name: str
    level: str
    timestamp: datetime
    message: str
    source_host: str | None = None
