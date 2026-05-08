"""REST API routes."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlmodel import Session, select, col

from beacon.api.deps import get_session, get_settings, require_token
from beacon.config import Settings
from beacon.models.log_entry import LogEntry, LogEntryCreate, LogEntryRead
from beacon.services.tasks import TaskSummary, delete_task_logs, list_task_summaries

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


@router.post("/log")
def ingest_log(
    payload: LogEntryCreate,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    timestamp = payload.timestamp or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    host = payload.host
    if host is None and request.client is not None:
        host = request.client.host

    entry = LogEntry(
        task_name=payload.task,
        level=payload.level.upper(),
        timestamp=timestamp,
        message=payload.message,
        source_host=host,
    )
    session.add(entry)
    session.commit()
    return {"ok": True}


@router.get("/tasks", response_model=list[TaskSummary])
def get_tasks(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[TaskSummary]:
    return list_task_summaries(
        session,
        running_window_seconds=settings.running_window_seconds,
    )


@router.get("/logs/{task}", response_model=list[LogEntryRead])
def get_logs(
    task: str,
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
    session: Session = Depends(get_session),
) -> list[LogEntryRead]:
    stmt = (
        select(LogEntry)
        .where(col(LogEntry.task_name) == task, col(LogEntry.id) > after_id)
        .order_by(col(LogEntry.id).asc())
        .limit(limit)
    )
    rows = session.exec(stmt).all()
    return [LogEntryRead.model_validate(row, from_attributes=True) for row in rows]


@router.delete("/tasks/{task}")
def delete_task(
    task: str,
    force: bool = Query(False, description="Delete even if the task looks active."),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, bool | int]:
    outcome, deleted = delete_task_logs(
        session,
        task,
        force=force,
        running_window_seconds=settings.running_window_seconds,
    )
    if outcome == "not_found":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="task not found")
    if outcome == "active":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="task is active (received logs recently); retry with force=true",
        )
    return {"ok": True, "deleted": deleted}
