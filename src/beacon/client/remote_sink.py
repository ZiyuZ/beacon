"""Loguru sink that ships log records to a Beacon server over HTTP.

Usage::

    from loguru import logger
    from beacon.client.remote_sink import remote_sink

    logger.add(
        remote_sink(
            url="https://beacon.example.com",
            task="training_a",
            token="secret-xyz",
        ),
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )

The returned callable is a Loguru sink: it accepts a ``loguru.Message``,
converts the underlying record into Beacon's JSON payload, and POSTs it.
Network and serialization errors are swallowed so a flaky server can never
take the script down. Pair with ``enqueue=True`` to keep logging off the
hot path.
"""

import socket
import sys
from typing import TYPE_CHECKING, Callable

import httpx

if TYPE_CHECKING:
    # ``Message`` only exists in loguru's stub file; importing it at runtime
    # raises ``ImportError``.
    from loguru import Message


def remote_sink(
    url: str,
    task: str,
    *,
    token: str | None = None,
    host: str | None = None,
    timeout: float = 3.0,
) -> Callable[["Message"], None]:
    """Build a Loguru sink that POSTs each record to ``{url}/api/log``."""

    endpoint = url.rstrip("/") + "/api/log"
    source_host = host or socket.gethostname()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    client = httpx.Client(timeout=timeout, headers=headers)

    def sink(message: "Message") -> None:
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
            # Don't call ``logger.exception`` here: the user's logger may
            # have ``remote_sink`` registered, which would re-enter this
            # function on every transport failure. Write to stderr instead.
            print(f"[beacon.remote_sink] {exc}", file=sys.stderr)

    return sink


__all__ = ["remote_sink"]
