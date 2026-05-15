Send Python script logs to a Beacon dashboard so they can be watched
live from a phone or browser. Use this skill when the user asks to set
up remote logging, monitor a long-running script, mirror Loguru output
to a dashboard, integrate with Beacon, push logs over HTTP, or wire a
crawler / training / job to a personal log panel. Beacon is a small
self-hosted FastAPI + SQLite + HTMX panel; one server runs in the
user's network, every script ships its log records to it via a single
HTTP POST per line. Keep the integration thin: do not install agents,
do not mount sockets, do not change the project's existing logger.

## When to use this skill

- The user mentions Beacon, "personal log dashboard", or wants to watch
  script logs from a phone.
- The user wants their existing Loguru / `logging` output mirrored to a
  remote URL with minimal effort.
- A script runs long (training, crawling, batch jobs) and the user
  wants live visibility without `tail -f` over SSH.

Skip if:

- The project already uses ELK / Loki / Datadog / Sentry — Beacon is
  a personal panel, not an enterprise stack.
- The script is short-lived and a final summary email is enough.

## What you need from the user

Ask once, in this order, only for fields you cannot guess:

1. **Server URL** — usually `http://<host>:44395`, the printed `Beacon
   listening on ...` line. If the user has a reverse proxy (Caddy /
   Nginx) it may be `https://beacon.example.com`.
2. **Bearer token** — printed in the server's `bearer token: ...`
   startup line, or sitting in `data/beacon.token` on the server. If
   the server runs with `--no-auth`, leave it empty.
3. **Task name** — short stable identifier per script (`training_a`,
   `crawler_news`, `nightly_eval`). One token can cover many tasks.

Recommend storing the URL and token in environment variables
(`BEACON_URL`, `BEACON_TOKEN`) rather than hard-coding them.

## Integration: Python + Loguru (preferred)

If the project uses [Loguru](https://github.com/Delgan/loguru), add a
sink. Keep the existing console / file sinks untouched.

### Step 1: pull in the sink

Two ways. Pick the one that matches the project's tooling.

**A. Add Beacon as a git dependency (uv project, recommended).**

```bash
uv add "beacon[client] @ git+https://github.com/ZiyuZ/beacon.git"
```

Then:

```python
from beacon.client import BeaconClient

beacon = BeaconClient(url=os.environ["BEACON_URL"], token=os.environ.get("BEACON_TOKEN"))
```

**B. Vendor the sink (no extra dependency).** Drop this file into the
project at `tools/beacon_sink.py` (or any path you prefer). Only
`httpx` is required — most modern projects already have it; if not,
`uv add httpx` (it is a 1MB pure-python wheel, no native deps).

```python
"""Loguru sink + BeaconClient that ships records to a Beacon server."""

import socket
import sys
from typing import TYPE_CHECKING, Callable

import httpx

if TYPE_CHECKING:
    from loguru import Message  # only present in stubs


class BeaconClient:
    """A client that maintains connection to a Beacon server.

    Configure the server URL and credentials once, then use ``.sink()``
    to get Loguru sinks and ``.mark_done()`` to signal completion.

    Usage::

        beacon = BeaconClient(url="http://beacon:8000", token="secret")
        logger.add(beacon.sink(task="training_a"), enqueue=True)
        beacon.mark_done(task="training_a")
    """

    def __init__(
        self,
        url: str,
        *,
        token: str | None = None,
        host: str | None = None,
        timeout: float = 3.0,
    ) -> None:
        self._base_url = url.rstrip("/")
        self._token = token
        self._default_host = host or socket.gethostname()
        self._timeout = timeout
        self._headers: dict[str, str] = {"Content-Type": "application/json"}
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    def sink(
        self,
        task: str,
        *,
        host: str | None = None,
    ) -> Callable[["Message"], None]:
        """Build a Loguru sink that POSTs records for *task*."""
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
        """Tell the Beacon server that *task* has finished."""
        endpoint = f"{self._base_url}/api/tasks/{task}/done"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                client.post(endpoint, headers=self._headers)
        except Exception as exc:
            print(f"[beacon.mark_done] {exc}", file=sys.stderr)
```
    url: str,
    task: str,
    *,
    token: str | None = None,
    timeout: float = 5.0,
) -> None:
    """Tell the Beacon server that *task* has finished.

    Posts to ``{url}/api/tasks/{task}/done`` which inserts a
    ``__TASK_DONE__`` sentinel so the task is shown as ``inactive``.
    Errors are swallowed so this never crashes the caller.
    """

    endpoint = f"{url.rstrip('/')}/api/tasks/{task}/done"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        with httpx.Client(timeout=timeout) as client:
            client.post(endpoint, headers=headers)
    except Exception as exc:
        print(f"[beacon.mark_done] {exc}", file=sys.stderr)
```

### Step 2: register the sink

In whatever module sets up logging (often `main.py`, `__init__.py`, a
`logging.py`, or near the entry point):

```python
import os
from loguru import logger

# Existing project sinks (console, file, ...) stay as-is.

beacon_url = os.environ.get("BEACON_URL")
beacon_token = os.environ.get("BEACON_TOKEN")  # may be None for --no-auth

if beacon_url:
    from tools.beacon_sink import BeaconClient  # or beacon.client.BeaconClient

    beacon = BeaconClient(url=beacon_url, token=beacon_token)

    logger.add(
        beacon.sink(task="training_a"),  # unique per script
        enqueue=True,         # ships records on a background thread
        backtrace=False,
        diagnose=False,
        level="INFO",         # avoid streaming DEBUG over the wire
    )
```

Three details that matter:

- `enqueue=True` is **non-negotiable**: it puts the HTTP call on a
  background thread, so a flaky network never blocks your hot path.
- `backtrace=False, diagnose=False` keeps payloads small and avoids
  leaking local variables / source lines through the network.
- Wrapping in `if beacon_url:` lets the same code run unchanged when
  the env var is not set (CI, offline dev, etc.).

### Step 3: surface task status (optional)

For long-running scripts, end every loop iteration with a heartbeat
log so Beacon's "running / inactive" detector knows you're alive even
when there is nothing interesting to say:

```python
logger.debug("alive epoch=%d", epoch)   # any line within ~30s is enough
```

Beacon flips a task to `inactive` after 30s of silence by default.

### Step 4: mark a task as done (optional)

When a script finishes cleanly you can explicitly tell Beacon the task
is complete so it shows as `inactive` immediately instead of waiting
for the time window to expire. This is purely cosmetic but helpful for
short scripts that finish before the 30s window.

Via the Python client — reuse the same ``BeaconClient``:

```python
beacon.mark_done(task="training_a")
```

Via the CLI:

```bash
uv run beacon-demo done training_a
```

Via curl:

```bash
curl -X POST "$BEACON_URL/api/tasks/training_a/done" \
  -H "Authorization: Bearer $BEACON_TOKEN"
```

Beacon inserts a `__TASK_DONE__` sentinel log entry. As soon as this
entry becomes the latest line for the task, the status flips to
`inactive`. If the script runs again and starts logging, a normal log
line overrides the sentinel and the task returns to `running`.

## Integration: stdlib `logging`

If the project uses the stdlib `logging` module, add a `Handler` that
posts to `/api/log`. Same payload shape, same auth.

```python
import logging
import os
import socket
from datetime import datetime, timezone

import httpx


class BeaconHandler(logging.Handler):
    def __init__(self, url: str, task: str, token: str | None = None) -> None:
        super().__init__()
        self._endpoint = url.rstrip("/") + "/api/log"
        self._task = task
        self._host = socket.gethostname()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(timeout=3.0, headers=headers)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._client.post(
                self._endpoint,
                json={
                    "task": self._task,
                    "level": record.levelname,
                    "message": self.format(record),
                    "timestamp": datetime.fromtimestamp(
                        record.created, tz=timezone.utc
                    ).isoformat(),
                    "host": self._host,
                },
            )
        except Exception:
            self.handleError(record)


root = logging.getLogger()
root.addHandler(
    BeaconHandler(
        url=os.environ["BEACON_URL"],
        task="training_a",
        token=os.environ.get("BEACON_TOKEN"),
    )
)
```

For high-throughput logging, wrap this in a `QueueHandler` +
`QueueListener` so HTTP calls do not block the producing thread.

## Integration: anything else (curl, Node, Go, shell)

The wire format is one POST per line. Anything that can speak HTTP
works. Minimal example:

```bash
curl -X POST "$BEACON_URL/api/log" \
  -H "Authorization: Bearer $BEACON_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"task":"deploy","level":"INFO","message":"started"}'
```

Required fields: `task`, `level`, `message`. Optional:
`timestamp` (ISO 8601 UTC, server fills in if absent) and `host`
(string, server uses request IP if absent).

## Conventions to follow

- **One task name per script**, stable across restarts. `training_a`
  not `training_a_2026_05_09`.
- **Levels**: stick to `DEBUG / INFO / WARNING / ERROR / CRITICAL`.
  Beacon colors `WARNING` yellow and `ERROR/CRITICAL` red, and a task
  with a recent `ERROR` shows the red `error` badge.
- **Multi-line tracebacks**: just include them as `\n` inside
  `message`. Beacon folds anything past the first line behind a
  `+N lines` summary, no escaping needed.
- **Don't log secrets / tokens / personal data**: there is no
  redaction layer; payloads land in SQLite as-is.
- **Don't put the bearer token in source control**. Read from env, a
  local `.env` (gitignored), or your deploy secret manager.

## Common patterns

### Multiple scripts in one repo

Give each its own task name; they all share the same URL and token:

```python
def setup_logging(task_name: str) -> None:
    if url := os.environ.get("BEACON_URL"):
        from tools.beacon_sink import BeaconClient  # or beacon.client.BeaconClient

        beacon = BeaconClient(url=url, token=os.environ.get("BEACON_TOKEN"))
        logger.add(
            beacon.sink(task=task_name),
            enqueue=True, backtrace=False, diagnose=False, level="INFO",
        )

# in train.py
setup_logging("training_a")

# in crawl.py
setup_logging("crawler_news")
```

### Cron / one-shot scripts

Add the sink **and** call `logger.complete()` (or `logging.shutdown()`)
before the process exits, so the background queue actually flushes:

```python
try:
    main()
finally:
    logger.complete()  # waits for enqueue=True worker to drain
```

Without this you can lose the last few lines of a fast-finishing
script.

### Multiple processes (multiprocessing / spawn)

Loguru's `enqueue=True` sink is process-safe, but if you `spawn`
workers, each new process must call `logger.add(beacon.sink(...))`
again — sinks do not survive `fork`/`spawn` automatically.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Logs never appear | Wrong URL or unreachable | Open `<url>/healthz` in a browser, expect `{"status":"ok"}` |
| `[beacon.sink] 401` on stderr | Missing or wrong bearer token | Re-check `BEACON_TOKEN`; on the server, `cat data/beacon.token` |
| Logs lag a few seconds | Server polls every 1s; sink uses `enqueue=True` | Expected; latency cap is ~1.5s |
| Last few lines missing on script exit | Background queue not flushed | `logger.complete()` in a `finally` block |
| Server's `/api/tasks` keeps showing `inactive` | No log within `BEACON_RUNNING_WINDOW_S` (30s) | Add a periodic `logger.debug("alive")` heartbeat, or increase the window via `--running-window-s` |
| Task is `inactive` too long after a `__TASK_DONE__` sentinel | That is expected | It stays inactive until a new log comes in — normal if the script is truly done |
| Server returns 409 on delete | Task is still active | User can confirm "delete anyway" in the UI; from CLI add `?force=true` |
| Task stays `running` after script exits | No `mark_done()` called, waiting for time window | Call `mark_done()` at end of script, or just wait `running_window_seconds` (default 30s) |
| `[beacon.mark_done]` on stderr | Network issue or wrong URL | Verify the server URL and that the task exists |
| Recursion / spam in stderr | Custom `logger.exception` inside a sink fallback | Beacon's sink uses `print(..., file=sys.stderr)` for this exact reason; do not replace it with `logger.exception` |

## Don't do this

- Do **not** try to write to Beacon's SQLite file directly from the
  script. Always go through `POST /api/log`.
- Do **not** put Beacon between the script and the user (e.g. as a
  required CI gate). It is a panel; if the panel is down the script
  must keep running. The provided sinks already swallow failures, do
  not re-raise them.
- Do **not** log every individual HTTP request from a busy server with
  `INFO` — Beacon stores everything, you will fill the SQLite file
  with noise. Aggregate or sample first.
- Do **not** create a new task per run (`task=f"job_{uuid}"`). The
  dashboard groups by task name; using a fresh name every run makes it
  unusable. Use one stable name and let timestamps differentiate runs.

## Reference

Beacon repository: <https://github.com/ZiyuZ/beacon>

API endpoints used by this skill:

- `POST /api/log` — write one log line. Required: `task`, `level`,
  `message`. Optional: `timestamp`, `host`. Returns `{"ok": true}`.
- `POST /api/tasks/{task}/done` — mark a task as finished. Inserts a
  `__TASK_DONE__` sentinel entry; the task flips to `inactive`.
  Returns `{"ok": true}`.
- `GET /health` — unauthenticated liveness probe.

All endpoints except `/health` require
`Authorization: Bearer <token>`. The read, delete, and done endpoints
also accept a JWT obtained from `POST /api/auth/login` (see the
server's startup output for the admin password).
