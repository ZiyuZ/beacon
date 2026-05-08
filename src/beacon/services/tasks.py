"""Task aggregation and status inference."""

from datetime import datetime, timedelta, timezone
from enum import Enum

from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select, col

from beacon.models.log_entry import LogEntry

ERROR_LEVELS = frozenset({"ERROR", "CRITICAL"})


class TaskStatus(str, Enum):
    running = "running"
    inactive = "inactive"
    error = "error"


class TaskSummary(BaseModel):
    task: str
    status: TaskStatus
    last_seen: datetime
    last_level: str
    last_message: str
    last_id: int


def _ensure_aware(dt: datetime) -> datetime:
    """SQLite stores naive datetimes; treat them as UTC."""

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def compute_status(
    last_seen: datetime,
    last_level: str,
    *,
    now: datetime | None = None,
    running_window_seconds: int = 30,
) -> TaskStatus:
    """Derive a task status from its most recent log entry.

    The order matters: a stale task is always ``inactive`` even if its last
    line was an error.
    """

    now = now or datetime.now(timezone.utc)
    if now - _ensure_aware(last_seen) > timedelta(seconds=running_window_seconds):
        return TaskStatus.inactive
    if last_level.upper() in ERROR_LEVELS:
        return TaskStatus.error
    return TaskStatus.running


def list_task_summaries(
    session: Session,
    *,
    now: datetime | None = None,
    running_window_seconds: int = 30,
) -> list[TaskSummary]:
    """Return one summary per task, ordered by recency."""

    # Pull the latest row per task by joining MAX(id) grouped by task_name back
    # to the table. Avoids window functions to stay friendly to SQLite.
    latest_id_subq = (
        select(LogEntry.task_name, func.max(LogEntry.id).label("max_id"))
        .group_by(LogEntry.task_name)
        .subquery()
    )

    stmt = (
        select(LogEntry)
        .join(latest_id_subq, col(LogEntry.id) == latest_id_subq.c.max_id)
        .order_by(col(LogEntry.timestamp).desc())
    )
    rows = session.exec(stmt).all()

    summaries: list[TaskSummary] = []
    for row in rows:
        status = compute_status(
            row.timestamp,
            row.level,
            now=now,
            running_window_seconds=running_window_seconds,
        )
        summaries.append(
            TaskSummary(
                task=row.task_name,
                status=status,
                last_seen=_ensure_aware(row.timestamp),
                last_level=row.level,
                last_message=row.message,
                last_id=row.id or 0,
            )
        )
    return summaries
