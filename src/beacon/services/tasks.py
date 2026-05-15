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

SENTINEL_LEVELS = frozenset(
    {TASK_DONE_LEVEL, TASK_CONNECT_LEVEL, TASK_DISCONNECT_LEVEL}
)


class TaskStatus(str, Enum):
    running = "running"
    inactive = "inactive"
    error = "error"
    crashed = "crashed"


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
    running_window_seconds: int = 1800,
    has_connect: bool = False,
) -> TaskStatus:
    """Derive a task status from its most recent log entry.

    Priority (first match wins):

    1. ``__TASK_DONE__`` or ``__TASK_DISCONNECT__`` → ``inactive`` (clean exit).
    2. Stale AND task has a ``__TASK_CONNECT__`` in its history → ``crashed``
       (the script was using ``BeaconClient`` but never sent a disconnect).
    3. Stale (no client, or legacy) → ``inactive``.
    4. Recent ``ERROR`` / ``CRITICAL`` → ``error``.
    5. Otherwise → ``running``.
    """

    now = now or datetime.now(timezone.utc)

    # 1. Clean exit
    if last_level.upper() in (TASK_DONE_LEVEL, TASK_DISCONNECT_LEVEL):
        return TaskStatus.inactive

    stale = now - _ensure_aware(last_seen) > timedelta(seconds=running_window_seconds)

    # 2. Stale + has CONNECT in history → crashed (script used BeaconClient
    #    but never sent a DISCONNECT / DONE before going silent).
    if stale and has_connect:
        return TaskStatus.crashed

    # 3. Stale, no CONNECT → inactive (legacy script, or genuinely idle)
    if stale:
        return TaskStatus.inactive

    # 4. Recent ERROR / CRITICAL
    if last_level.upper() in ERROR_LEVELS:
        return TaskStatus.error

    # 5. Running
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

    # Check which tasks have a __TASK_CONNECT__ in their history.
    # Used to detect crashes: if a task ever called ``BeaconClient.sink()``
    # but went silent without a DISCONNECT / DONE, it likely crashed.
    connect_subq = (
        select(LogEntry.task_name)
        .where(col(LogEntry.level) == TASK_CONNECT_LEVEL)
        .distinct()
        .subquery()
    )
    connect_tasks = {r[0] for r in session.exec(select(connect_subq)).all()}

    summaries: list[TaskSummary] = []
    for row in rows:
        status = compute_status(
            row.timestamp,
            row.level,
            now=now,
            running_window_seconds=running_window_seconds,
            has_connect=row.task_name in connect_tasks,
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


def delete_inactive_task_logs(
    session: Session,
    *,
    running_window_seconds: int,
    now: datetime | None = None,
) -> tuple[int, int]:
    """Delete logs for every currently inactive task.

    Returns ``(tasks_deleted, rows_deleted)``.
    """

    summaries = list_task_summaries(
        session,
        now=now,
        running_window_seconds=running_window_seconds,
    )
    inactive_tasks = [s.task for s in summaries if s.status == TaskStatus.inactive]
    if not inactive_tasks:
        return (0, 0)

    count_stmt = (
        select(func.count())
        .select_from(LogEntry)
        .where(col(LogEntry.task_name).in_(inactive_tasks))
    )
    total_rows = session.exec(count_stmt).one()
    if total_rows == 0:
        return (0, 0)

    del_stmt = delete(LogEntry).where(col(LogEntry.task_name).in_(inactive_tasks))
    session.exec(del_stmt)
    session.commit()
    return (len(inactive_tasks), total_rows)
