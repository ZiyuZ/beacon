"""FastAPI application factory and HTML routes."""

from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select, col

from beacon.api import router as api_router
from beacon.api.deps import get_session, get_settings
from beacon.config import Settings
from beacon.database import create_db_and_tables
from beacon.models.log_entry import LogEntry, LogEntryRead
from beacon.services.tasks import list_task_summaries

_TEMPLATES_DIR = Path(str(files("beacon").joinpath("templates")))
_FAVICON_PATH = _TEMPLATES_DIR / "favicon.svg"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@asynccontextmanager
async def _lifespan(_: FastAPI):
    create_db_and_tables()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Beacon", lifespan=_lifespan)
    app.include_router(api_router)

    @app.get("/favicon.svg")
    def favicon_svg() -> FileResponse:
        return FileResponse(_FAVICON_PATH, media_type="image/svg+xml")

    @app.get("/", response_class=HTMLResponse)
    def tasks_page(
        request: Request,
        session: Session = Depends(get_session),
        settings: Settings = Depends(get_settings),
    ) -> HTMLResponse:
        tasks = list_task_summaries(
            session,
            running_window_seconds=settings.running_window_seconds,
        )
        return templates.TemplateResponse(
            request,
            "tasks.html",
            {"tasks": tasks},
        )

    @app.get("/tasks/{task}", response_class=HTMLResponse)
    def task_detail(request: Request, task: str) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "task_logs.html",
            {"task": task},
        )

    @app.get("/partials/tasks", response_class=HTMLResponse)
    def task_list_partial(
        request: Request,
        session: Session = Depends(get_session),
        settings: Settings = Depends(get_settings),
    ) -> HTMLResponse:
        tasks = list_task_summaries(
            session,
            running_window_seconds=settings.running_window_seconds,
        )
        return templates.TemplateResponse(
            request,
            "partials/task_list.html",
            {"tasks": tasks},
        )

    @app.get("/partials/logs/{task}", response_class=HTMLResponse)
    def log_lines_partial(
        request: Request,
        task: str,
        after_id: int = Query(default=0, ge=0),
        limit: int = Query(default=500, ge=1, le=2000),
        session: Session = Depends(get_session),
    ) -> HTMLResponse:
        stmt = (
            select(LogEntry)
            .where(col(LogEntry.task_name) == task, col(LogEntry.id) > after_id)
            .order_by(col(LogEntry.id).asc())
            .limit(limit)
        )
        rows = session.exec(stmt).all()
        entries = [
            LogEntryRead.model_validate(row, from_attributes=True) for row in rows
        ]
        return templates.TemplateResponse(
            request,
            "partials/log_lines.html",
            {"entries": entries},
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
