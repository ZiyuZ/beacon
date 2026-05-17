"""System snapshot model — periodic CPU/GPU/memory/load telemetry."""

from datetime import datetime, timezone

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SystemSnapshotBase(SQLModel):
    task_name: str = Field(index=True, max_length=128)
    source_host: str | None = Field(default=None, max_length=128)
    timestamp: datetime = Field(default_factory=_utcnow, index=True)
    collection_interval: float = Field(default=10.0)

    cpu_percent: float | None = Field(default=None)
    memory_percent: float | None = Field(default=None)
    memory_used_mb: float | None = Field(default=None)
    memory_total_mb: float | None = Field(default=None)
    gpu_percent: float | None = Field(default=None)
    gpu_memory_percent: float | None = Field(default=None)
    gpu_memory_used_mb: float | None = Field(default=None)
    gpu_memory_total_mb: float | None = Field(default=None)
    load_1m: float | None = Field(default=None)
    load_5m: float | None = Field(default=None)
    load_15m: float | None = Field(default=None)


class SystemSnapshot(SystemSnapshotBase, table=True):
    __tablename__ = "system_snapshots"
    __table_args__ = (Index("ix_sys_snapshots_task_id", "task_name", "id"),)

    id: int | None = Field(default=None, primary_key=True)


class SystemSnapshotCreate(SQLModel):
    """Payload accepted by ``POST /api/sys-stats``."""

    task: str
    host: str | None = None
    timestamp: datetime | None = None
    collection_interval: float = 10.0
    cpu_percent: float | None = None
    memory_percent: float | None = None
    memory_used_mb: float | None = None
    memory_total_mb: float | None = None
    gpu_percent: float | None = None
    gpu_memory_percent: float | None = None
    gpu_memory_used_mb: float | None = None
    gpu_memory_total_mb: float | None = None
    load_1m: float | None = None
    load_5m: float | None = None
    load_15m: float | None = None


class SystemSnapshotRead(SQLModel):
    """Per-row response returned to clients and templates."""

    id: int
    task_name: str
    source_host: str | None = None
    timestamp: datetime
    collection_interval: float
    cpu_percent: float | None = None
    memory_percent: float | None = None
    memory_used_mb: float | None = None
    memory_total_mb: float | None = None
    gpu_percent: float | None = None
    gpu_memory_percent: float | None = None
    gpu_memory_used_mb: float | None = None
    gpu_memory_total_mb: float | None = None
    load_1m: float | None = None
    load_5m: float | None = None
    load_15m: float | None = None
    fresh: bool = True
