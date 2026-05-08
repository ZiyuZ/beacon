"""Command-line entry point for Beacon.

Defines the ``beacon`` console script. The CLI is intentionally thin: every
option just forwards to ``uvicorn`` and/or environment variables that the
FastAPI app already reads via :mod:`beacon.config`.
"""

import os
import secrets
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

import typer

DEFAULT_SQLITE_PATH = Path("data/beacon.db")
TOKEN_FILENAME = "beacon.token"

app = typer.Typer(
    name="beacon",
    help="Beacon - lightweight personal log dashboard.",
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _resolve_version() -> str:
    try:
        return _pkg_version("beacon")
    except PackageNotFoundError:
        return "0.0.0+local"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(_resolve_version())
        raise typer.Exit()


def _ensure_token(db_path: Path) -> str:
    """Return a persistent token, creating one next to the SQLite file if needed.

    The token is stored in ``<db dir>/beacon.token`` so it survives restarts
    (clients keep working) but lives in the same gitignored ``data/`` volume
    as the database.
    """

    token_file = db_path.parent / TOKEN_FILENAME
    if token_file.exists():
        existing = token_file.read_text(encoding="utf-8").strip()
        if existing:
            return existing

    token = secrets.token_urlsafe(32)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(token, encoding="utf-8")
    try:
        # Best-effort POSIX permissions; on Windows this is a no-op.
        os.chmod(token_file, 0o600)
    except OSError:
        pass
    return token


@app.command()
def serve(
    host: str = typer.Option(
        "0.0.0.0",
        "--host",
        help="Bind host. Default 0.0.0.0 so the phone on your LAN can reach it.",
    ),
    port: int = typer.Option(8000, "--port", "-p", help="Bind port."),
    reload: bool = typer.Option(
        False,
        "--reload",
        help="Auto-reload on source changes (development only).",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        envvar="BEACON_API_TOKEN",
        help="Shared bearer token. Auto-generated and persisted if omitted.",
        show_envvar=True,
    ),
    no_auth: bool = typer.Option(
        False,
        "--no-auth",
        help="Disable bearer auth entirely (local trusted networks only).",
    ),
    db: Path | None = typer.Option(
        None,
        "--db",
        envvar="BEACON_SQLITE_PATH",
        help="SQLite path. Defaults to ./data/beacon.db.",
        show_envvar=True,
    ),
    running_window_s: int | None = typer.Option(
        None,
        "--running-window-s",
        envvar="BEACON_RUNNING_WINDOW_S",
        help="Seconds without logs before a task is considered inactive.",
        show_envvar=True,
        min=1,
    ),
    log_level: str = typer.Option(
        "info",
        "--log-level",
        case_sensitive=False,
        help="Uvicorn log level.",
    ),
    workers: int = typer.Option(
        1,
        "--workers",
        min=1,
        help="Worker count. Keep at 1 unless you front it with shared storage.",
    ),
    _version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Start the Beacon log dashboard."""

    db_path = (db if db is not None else DEFAULT_SQLITE_PATH).resolve()
    os.environ["BEACON_SQLITE_PATH"] = str(db_path)
    if running_window_s is not None:
        os.environ["BEACON_RUNNING_WINDOW_S"] = str(running_window_s)

    if no_auth:
        if token:
            raise typer.BadParameter("--no-auth and --token are mutually exclusive.")
        os.environ["BEACON_API_TOKEN"] = ""
    else:
        effective_token = token or _ensure_token(db_path)
        os.environ["BEACON_API_TOKEN"] = effective_token

    typer.secho(
        f"Beacon listening on http://{host}:{port}",
        fg=typer.colors.GREEN,
        err=True,
    )
    if no_auth:
        typer.secho(
            "  auth: DISABLED (--no-auth). Anyone reaching this port can write logs.",
            fg=typer.colors.YELLOW,
            err=True,
        )
    else:
        typer.secho(
            f"  bearer token: {os.environ['BEACON_API_TOKEN']}",
            fg=typer.colors.CYAN,
            err=True,
        )
    typer.secho(f"  sqlite: {db_path}", fg=typer.colors.BRIGHT_BLACK, err=True)

    import uvicorn

    uvicorn.run(
        "beacon.main:app",
        host=host,
        port=port,
        reload=reload,
        workers=workers if not reload else 1,
        log_level=log_level.lower(),
    )


if __name__ == "__main__":  # pragma: no cover - manual invocation
    app()
