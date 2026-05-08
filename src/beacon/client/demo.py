"""Demo CLI: stream fake training logs to a Beacon server.

Useful for end-to-end smoke tests and for populating the dashboard while you
fiddle with the UI. Does not depend on ``loguru``; talks directly to
``/api/log`` with ``httpx``.
"""

from __future__ import annotations

import os
import random
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import typer

DEFAULT_URL = "http://127.0.0.1:8000"
DEFAULT_TOKEN_FILE = Path("data/beacon.token")

app = typer.Typer(
    name="beacon-demo",
    help="Stream fake logs to a Beacon server for end-to-end testing.",
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


_NORMAL_LINES = [
    "step={step} loss={loss:.4f} acc={acc:.3f}",
    "checkpoint saved to ckpt_{step}.pt",
    "evaluating on val set, batch {step}",
    "lr={lr:.5f} grad_norm={gn:.3f}",
    "data loader at {pct} samples/s",
]
_WARN_LINES = [
    "gpu utilization at {pct}%, throttling soon",
    "skipping batch {step} due to NaN",
    "early stop patience {p}/5",
]
_ERROR_LINES = [
    "CUDA out of memory at step {step}",
    "checkpoint at ckpt_{step}.pt is corrupted, retrying",
    "lost connection to data server, reconnecting",
    (
        "Traceback (most recent call last):\n"
        '  File "train.py", line 42, in <module>\n'
        '    raise RuntimeError("epoch budget exhausted")\n'
        "RuntimeError: epoch budget exhausted"
    ),
]

_LEVEL_COLOR = {
    "DEBUG": typer.colors.WHITE,
    "INFO": typer.colors.BLUE,
    "WARNING": typer.colors.YELLOW,
    "ERROR": typer.colors.RED,
    "CRITICAL": typer.colors.BRIGHT_RED,
}


def _resolve_token(explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    env_token = os.environ.get("BEACON_API_TOKEN")
    if env_token:
        return env_token
    if DEFAULT_TOKEN_FILE.exists():
        text = DEFAULT_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if text:
            return text
    return None


def _make_payload(task: str, step: int) -> dict:
    bucket = random.random()
    if bucket < 0.85:
        level = "INFO" if random.random() < 0.92 else "DEBUG"
        msg = random.choice(_NORMAL_LINES).format(
            step=step,
            loss=max(0.001, 1.5 * (0.95**step) + random.uniform(-0.05, 0.05)),
            acc=min(0.999, 0.5 + step * 0.005 + random.uniform(-0.02, 0.02)),
            lr=0.001 * (0.99**step),
            gn=random.uniform(0.5, 5.0),
            pct=random.randint(800, 5000),
        )
    elif bucket < 0.95:
        level = "WARNING"
        msg = random.choice(_WARN_LINES).format(
            step=step,
            pct=random.randint(80, 99),
            p=random.randint(1, 5),
        )
    else:
        level = "ERROR" if random.random() < 0.85 else "CRITICAL"
        msg = random.choice(_ERROR_LINES).format(step=step)

    return {
        "task": task,
        "level": level,
        "message": msg,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "host": socket.gethostname(),
    }


@app.command()
def demo(
    task: str = typer.Argument(
        "demo_task",
        help="Task name as it appears on the dashboard.",
    ),
    url: str = typer.Option(
        DEFAULT_URL,
        "--url",
        "-u",
        help="Beacon server base URL.",
    ),
    token: Optional[str] = typer.Option(
        None,
        "--token",
        envvar="BEACON_API_TOKEN",
        show_envvar=True,
        help=(
            "Bearer token. Falls back to env BEACON_API_TOKEN, "
            f"then to ./{DEFAULT_TOKEN_FILE.as_posix()}."
        ),
    ),
    interval: float = typer.Option(
        1.0, "--interval", "-i", min=0.05, help="Pause between logs (seconds)."
    ),
    count: Optional[int] = typer.Option(
        None, "--count", "-n", min=1, help="Stop after N logs (default: forever)."
    ),
    message: Optional[str] = typer.Option(
        None,
        "--message",
        "-m",
        help="Send a single explicit message instead of generated ones (implies --count 1).",
    ),
    level: str = typer.Option(
        "INFO",
        "--level",
        "-L",
        help="Level used together with --message.",
        case_sensitive=False,
    ),
) -> None:
    """Stream fake training logs to a Beacon server."""

    resolved = _resolve_token(token)
    headers = {"Content-Type": "application/json"}
    if resolved:
        headers["Authorization"] = f"Bearer {resolved}"

    target_count = 1 if message is not None else count

    typer.secho(
        f"-> {url}/api/log as task='{task}', every {interval:.2f}s"
        + (
            f", {target_count} log(s)" if target_count else ", forever (Ctrl+C to stop)"
        ),
        fg=typer.colors.CYAN,
        err=True,
    )
    if not resolved:
        typer.secho(
            "  no token resolved; assuming server is running with --no-auth",
            fg=typer.colors.YELLOW,
            err=True,
        )

    sent = 0
    failed = 0
    endpoint = f"{url.rstrip('/')}/api/log"

    with httpx.Client(timeout=5.0, headers=headers) as client:
        try:
            while target_count is None or (sent + failed) < target_count:
                if message is not None:
                    payload = {
                        "task": task,
                        "level": level.upper(),
                        "message": message,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "host": socket.gethostname(),
                    }
                else:
                    payload = _make_payload(task, sent)

                try:
                    response = client.post(endpoint, json=payload)
                    if response.status_code >= 400:
                        failed += 1
                        typer.secho(
                            f"  HTTP {response.status_code}: {response.text[:120]}",
                            fg=typer.colors.RED,
                            err=True,
                        )
                    else:
                        sent += 1
                        first_line = payload["message"].splitlines()[0]
                        typer.secho(
                            f"  [{payload['level']:<8}] {first_line[:96]}",
                            fg=_LEVEL_COLOR.get(payload["level"], typer.colors.WHITE),
                        )
                except httpx.HTTPError as exc:
                    failed += 1
                    typer.secho(
                        f"  network error: {exc}", fg=typer.colors.RED, err=True
                    )

                if target_count is not None and (sent + failed) >= target_count:
                    break
                time.sleep(interval)
        except KeyboardInterrupt:
            pass

    typer.secho(
        f"done: {sent} sent, {failed} failed",
        fg=typer.colors.CYAN,
        err=True,
    )
    if failed and not sent:
        raise typer.Exit(code=1)


if __name__ == "__main__":  # pragma: no cover
    app()
