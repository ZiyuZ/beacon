"""Task aggregation and status inference."""

from datetime import datetime, timedelta, timezone
from enum import Enum

from pydantic import BaseModel
from sqlalchemy import delete, func
from sqlmodel import Session, select, col

from beacon.models.log_entry import LogEntry

ERROR_LEVELS = frozenset({"ERROR", "CRITICAL"})
TASK_DONE_LEVEL = "__TASK_DONE__"
TASK_CONNECT_LEVEL = "__TASK_CONNECT__"
TASK_DISCONNECT_LEVEL = "__TASK_DISCONNECT__"
TASK_HEARTBEAT_LEVEL = "__TASK_HEARTBEAT__"

SENTINEL_LEVELS = frozenset(
    {TASK_DONE_LEVEL, TASK_CONNECT_LEVEL, TASK_DISCONNECT_LEVEL, TASK_HEARTBEAT_LEVEL}
)


class TaskStatus(str, Enum):
    running = "running"
    disconnected = "disconnected"
    error = "error"


class TaskSummary(BaseModel):
    task: str
    status: TaskStatus
    last_seen: datetime
    last_level: str
    last_message: str
    last_id: int
    display_level: str | None = None
    display_message: str | None = None


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
    running_window_seconds: int = 1800,
    heartbeat_timeout: int = 0,
) -> TaskStatus:
    """Derive a task status from its most recent log entry.

    Priority (first match wins):

    1. ``__TASK_DONE__`` or ``__TASK_DISCONNECT__`` → ``disconnected`` (clean exit).
    2. Stale (by ``heartbeat_timeout``) + latest is ``__TASK_HEARTBEAT__`` →
       ``disconnected`` (heartbeat stopped).
    3. Recent ``ERROR`` / ``CRITICAL`` → ``error``.
    4. Stale (by ``running_window_seconds``) → ``disconnected``.
    5. Otherwise → ``running``.
    """

    now = now or datetime.now(timezone.utc)

    if last_level.upper() in (TASK_DONE_LEVEL, TASK_DISCONNECT_LEVEL):
        return TaskStatus.disconnected

    age = now - _ensure_aware(last_seen)

    if (
        heartbeat_timeout > 0
        and last_level.upper() == TASK_HEARTBEAT_LEVEL
        and age > timedelta(seconds=heartbeat_timeout)
    ):
        return TaskStatus.disconnected

    if last_level.upper() in ERROR_LEVELS:
        return TaskStatus.error

    stale = age > timedelta(seconds=running_window_seconds)

    if stale:
        return TaskStatus.disconnected

    return TaskStatus.running


def list_task_summaries(
    session: Session,
    *,
    now: datetime | None = None,
    running_window_seconds: int = 1800,
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

    # Also fetch the latest non-sentinel entry per task for display.
    latest_display_subq = (
        select(LogEntry.task_name, func.max(LogEntry.id).label("max_id"))
        .where(col(LogEntry.level).notin_(SENTINEL_LEVELS))
        .group_by(LogEntry.task_name)
        .subquery()
    )
    display_stmt = select(LogEntry).join(
        latest_display_subq, col(LogEntry.id) == latest_display_subq.c.max_id
    )
    display_rows: dict[str, LogEntry] = {
        r.task_name: r for r in session.exec(display_stmt).all()
    }

    summaries: list[TaskSummary] = []
    for row in rows:
        # If the latest entry is a HEARTBEAT, use a shorter timeout (30s)
        # for fast disconnection detection.
        hb_timeout = (
            min(running_window_seconds, 30) if row.level == TASK_HEARTBEAT_LEVEL else 0
        )
        status = compute_status(
            row.timestamp,
            row.level,
            now=now,
            running_window_seconds=running_window_seconds,
            heartbeat_timeout=hb_timeout,
        )
        # Use the latest non-sentinel entry for display fields.
        display_row = display_rows.get(row.task_name)
        summaries.append(
            TaskSummary(
                task=row.task_name,
                status=status,
                last_seen=_ensure_aware(row.timestamp),
                last_level=row.level,
                last_message=row.message,
                last_id=row.id or 0,
                display_level=display_row.level if display_row else None,
                display_message=display_row.message if display_row else None,
            )
        )
    return summaries


def delete_task_logs(
    session: Session,
    task_name: str,
    *,
    force: bool,
    running_window_seconds: int,
    now: datetime | None = None,
) -> tuple[str, int]:
    """Remove every ``LogEntry`` row for ``task_name``.

    Returns ``('deleted', n)``, ``('not_found', 0)``, or ``('active', 0)``
    when the latest-derived status is ``running`` and ``force`` is false.
    """

    count_stmt = (
        select(func.count())
        .select_from(LogEntry)
        .where(col(LogEntry.task_name) == task_name)
    )
    total = session.exec(count_stmt).one()
    if total == 0:
        return ("not_found", 0)

    if not force:
        summaries = list_task_summaries(
            session,
            now=now,
            running_window_seconds=running_window_seconds,
        )
        for s in summaries:
            if s.task == task_name and s.status == TaskStatus.running:
                return ("active", 0)

    del_stmt = delete(LogEntry).where(col(LogEntry.task_name) == task_name)
    session.exec(del_stmt)
    session.commit()
    return ("deleted", total)


def delete_finished_task_logs(
    session: Session,
    *,
    running_window_seconds: int,
    now: datetime | None = None,
) -> tuple[int, int]:
    """Delete logs for every finished (disconnected) task.

    Returns ``(tasks_deleted, rows_deleted)``.
    """

    summaries = list_task_summaries(
        session,
        now=now,
        running_window_seconds=running_window_seconds,
    )
    finishable = [s.task for s in summaries if s.status == TaskStatus.disconnected]
    if not finishable:
        return (0, 0)

    count_stmt = (
        select(func.count())
        .select_from(LogEntry)
        .where(col(LogEntry.task_name).in_(finishable))
    )
    total_rows = session.exec(count_stmt).one()
    if total_rows == 0:
        return (0, 0)

    del_stmt = delete(LogEntry).where(col(LogEntry.task_name).in_(finishable))
    session.exec(del_stmt)
    session.commit()
    return (len(finishable), total_rows)
