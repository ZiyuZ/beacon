"""REST API routes."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlmodel import Session, select, col

from beacon.api.deps import (
    create_login_jwt,
    get_session,
    get_settings,
    require_token,
)
from beacon.config import Settings
from beacon.models.log_entry import LogEntry, LogEntryCreate, LogEntryRead
from beacon.services.tasks import (
    TASK_DONE_LEVEL,
    TaskSummary,
    delete_inactive_task_logs,
    delete_task_logs,
    list_task_summaries,
)

# ── Auth router (no token required) ──────────────────────────────────────

auth_router = APIRouter(prefix="/api/auth")


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@auth_router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest, settings: Settings = Depends(get_settings)
) -> LoginResponse:
    if not settings.admin_password:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="admin password is not configured",
        )
    if payload.password != settings.admin_password:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="incorrect password",
        )
    token = create_login_jwt(settings.admin_password)
    return LoginResponse(access_token=token)


# ── Main API router (token / JWT required) ──────────────────────────────

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


def _normalize_payload_timestamp(ts: datetime) -> datetime:
    """Normalize incoming timestamps to UTC.

    If clients send naive datetimes, treat them as server-local wall-clock time.
    This matches common script behavior (`datetime.now().isoformat()`) and avoids
    accidentally shifting timestamps into the future by interpreting naive values
    as UTC.
    """

    if ts.tzinfo is None:
        local_tz = datetime.now().astimezone().tzinfo or timezone.utc
        ts = ts.replace(tzinfo=local_tz)
    return ts.astimezone(timezone.utc)


@router.post("/log")
def ingest_log(
    payload: LogEntryCreate,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    timestamp = payload.timestamp or datetime.now(timezone.utc)
    timestamp = _normalize_payload_timestamp(timestamp)

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


@router.delete("/tasks")
def delete_inactive_tasks(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, bool | int]:
    tasks_deleted, rows_deleted = delete_inactive_task_logs(
        session,
        running_window_seconds=settings.running_window_seconds,
    )
    return {
        "ok": True,
        "deleted_tasks": tasks_deleted,
        "deleted_rows": rows_deleted,
    }


@router.post("/tasks/{task}/done", response_model=dict[str, bool])
def mark_task_done(
    task: str,
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    """Mark *task* as finished by inserting a ``__TASK_DONE__`` sentinel entry.

    Once the sentinel becomes the latest log for the task, ``compute_status``
    will return ``inactive`` regardless of the time window.
    """

    host = request.client.host if request.client is not None else None

    entry = LogEntry(
        task_name=task,
        level=TASK_DONE_LEVEL,
        timestamp=datetime.now(timezone.utc),
        message="Task marked as done",
        source_host=host,
    )
    session.add(entry)
    session.commit()
    return {"ok": True}
