"""Loguru sink that ships log records to a Beacon server over HTTP.

Usage::

    from beacon.client import BeaconClient

    # URL and token are auto-resolved from env / local file if omitted.
    beacon = BeaconClient()

    # For Loguru — one .sink() per task name
    logger.add(
        beacon.sink(task="training_a"),
        enqueue=True, backtrace=False, diagnose=False,
    )

    # Mark a task as done
    beacon.mark_done(task="training_a")
"""

import os
import socket
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import httpx

if TYPE_CHECKING:
    # ``Message`` only exists in loguru's stub file; importing it at runtime
    # raises ``ImportError``.
    from loguru import Message


def _resolve_url(url: str | None) -> str:
    if url is not None:
        return url
    env = os.environ.get("BEACON_URL")
    if env:
        return env
    return "http://127.0.0.1:8000"


def _resolve_token(token: str | None) -> str | None:
    if token is not None:
        return token
    env = os.environ.get("BEACON_API_TOKEN")
    if env:
        return env
    token_file = Path("data/beacon.token")
    if token_file.exists():
        text = token_file.read_text(encoding="utf-8").strip()
        if text:
            return text
    return None


class BeaconClient:
    """A client that maintains connection to a Beacon server.

    Configure the server URL and credentials once, then use ``.sink()``
    to get Loguru sinks and ``.mark_done()`` to signal task completion.

    If *url* or *token* are ``None`` they are resolved automatically:

    * *url* → ``BEACON_URL`` env var → ``http://127.0.0.1:8000``
    * *token* → ``BEACON_API_TOKEN`` env var → ``data/beacon.token`` file

    Usage::

        beacon = BeaconClient()                              # auto-resolve
        beacon = BeaconClient(url="http://beacon:8000")      # explicit url
        beacon = BeaconClient(token="secret")                 # explicit token
    """

    def __init__(
        self,
        url: str | None = None,
        *,
        token: str | None = None,
        host: str | None = None,
        timeout: float = 3.0,
    ) -> None:
        self._base_url = _resolve_url(url).rstrip("/")
        self._default_host = host or socket.gethostname()
        self._timeout = timeout

        resolved_token = _resolve_token(token)
        self._headers: dict[str, str] = {}
        if resolved_token:
            self._headers["Authorization"] = f"Bearer {resolved_token}"

    def sink(
        self,
        task: str,
        *,
        host: str | None = None,
    ) -> Callable[["Message"], None]:
        """Build a Loguru sink that POSTs records for *task*.

        The returned callable accepts a ``loguru.Message`` and POSTs it
        to the server. Network errors are swallowed so a flaky server
        never takes down the caller.
        """

        endpoint = f"{self._base_url}/api/log"
        source_host = host or self._default_host
        client = httpx.Client(timeout=self._timeout, headers=self._headers)

        def _sink(message: "Message") -> None:
            record = message.record
            payload = {
                "task": task,
                "level": record["level"].name,
                "message": record["message"],
                "timestamp": record["time"].isoformat(),
                "host": source_host,
            }
            try:
                client.post(endpoint, json=payload)
            except Exception as exc:
                print(f"[beacon.sink] {exc}", file=sys.stderr)

        return _sink

    def mark_done(self, task: str) -> None:
        """Tell the Beacon server that *task* has finished.

        Posts to ``/api/tasks/{task}/done`` which inserts a
        ``__TASK_DONE__`` sentinel so the task shows as ``inactive``.
        """

        endpoint = f"{self._base_url}/api/tasks/{task}/done"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                client.post(endpoint, headers=self._headers)
        except Exception as exc:
            print(f"[beacon.mark_done] {exc}", file=sys.stderr)


__all__ = ["BeaconClient"]
