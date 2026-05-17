<!-- markdownlint-disable MD013 MD033 MD041 -->
<p align="right">
  English | <a href="./README.zh-CN.md">简体中文</a>
</p>

# Beacon

A lightweight personal log dashboard. Your scripts push logs over HTTP, you
watch them live from a phone or laptop. SQLite + FastAPI + HTMX, no agents,
no observability stack to babysit.

![Status](https://img.shields.io/badge/status-alpha-orange)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)

## What it is

- **Server** (`beacon`): FastAPI app with REST endpoints and a small
  HTMX UI; data lives in a single SQLite file. Supports JWT login for
  browser sessions alongside the classic bearer token for scripts.
- **Client** (`beacon.client.BeaconClient`): a Loguru sink that ships
  records to the server, plus a `beacon-demo` CLI for testing.
- **Status inference**: `running` (receiving logs), `error` (latest is
  `ERROR`/`CRITICAL`), `disconnected` (silent for 30s with heartbeat,
  or 30min without), `disconnected` (all finished states).
  Tasks can be explicitly marked as done via `POST /api/tasks/{task}/done`.
- **Heartbeat** (`BeaconClient(heartbeat=10)`): optional automatic keep-alive.
  When enabled, the client sends a lightweight heartbeat every N seconds.
  If heartbeats stop, the server detects disconnection within ~30s and
  marks the task as `disconnected`. Heartbeat entries are hidden from
  the log view automatically.
- **System stats** (`BeaconClient(stats_interval=10)`): optional periodic
  CPU / memory / GPU / load telemetry. Collected via `psutil` and
  `nvidia-smi` (no extra dependencies). Displayed as live gauge cards
  on the task detail page and as compact bars on the task list.
  Stale data (3× the collection interval without updates) fades to gray.

What it is not: an ELK/Loki replacement, a multi-user system, an SSH
terminal. It is a personal panel for a handful of long-running scripts.

## Quick start

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/ZiyuZ/beacon.git
cd beacon
uv sync --extra server
uv run beacon
```

On first start the server prints a generated bearer token, an admin
password for Web UI login, and the SQLite path, then listens on
`0.0.0.0:8000`:

```text
Beacon listening on http://0.0.0.0:8000
  bearer token: NSxxxxxxxxxxxxxxxxxxxxxxxxxxxx
  admin password: xxxxxxxxxxxxxxxx
  sqlite: /app/beacon/data/beacon.db
```

The token is persisted to `data/beacon.token` so subsequent restarts reuse
it. Open the printed URL on your phone (LAN reachable thanks to `0.0.0.0`)
and you should see the empty dashboard.

To make sure things wire end-to-end, push a few fake logs in another shell:

```bash
uv run beacon-demo training_a -i 0.5
```

`beacon-demo` reads the same `data/beacon.token`, so you do not need to
copy the token around for local testing.

## Installation

Beacon's dependencies are split so you only install what you need.

| Install command | What you get | Use case |
|---|---|---|
| `uv add "beacon @ git+..."` | `httpx` + `typer` | Lightest: use `BeaconClient`, `mark_done()`, `beacon-demo` CLI |
| `uv add "beacon[client] @ git+..."` | ↑ + `loguru` | Add the Loguru sink (`beacon.sink(task=...)`) |
| `uv add "beacon[server] @ git+..."` | ↑ + server deps | Run the Beacon server itself |

If you have the repo cloned locally:

```bash
uv add --editable "../beacon"           # client only
uv add --editable "../beacon[server]"   # full server
```

## Sending real logs from your scripts

Then add the sink to your existing Loguru setup:

```python
from loguru import logger
from beacon.client import BeaconClient

beacon = BeaconClient(
    url="http://your-server:8000",
    token="NSxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    heartbeat=10,       # optional: auto heartbeat every 10s
    stats_interval=10,  # optional: collect CPU/GPU/load every 10s
)

logger.add(
    beacon.sink(task="training_a"),
    enqueue=True,       # never block the hot path
    backtrace=False,
    diagnose=False,
)

logger.info("started")
```

### System stats (optional)

Enable periodic system telemetry collection with `stats_interval`:

```python
beacon = BeaconClient(
    url="http://your-server:8000",
    token="NSxxxx",
    stats_interval=10,  # seconds between snapshots
)
```

The client collects CPU %, memory %, GPU util, GPU VRAM, and system
load (1m / 5m / 15m) using `psutil` and `nvidia-smi`, then POSTs them
to the server. GPU detection happens automatically when `nvidia-smi`
is available — no extra libraries needed.

The server uses the client's `collection_interval` to infer staleness:
data older than `3 × interval` is marked stale and displayed as gray
cards. If telemetry stops, the UI shows "stale" after ~3 missed cycles.

Stats appear as:
- **Task detail page**: 5 gauge cards (CPU / Memory / GPU / VRAM / Load)
  with progress bars and color gradients. Refreshed via HTMX every 8s.
- **Task list page**: compact bars next to each task (CPU / MEM / GPU).

### Task lifecycle (automatic)

When using `BeaconClient`, task status is managed automatically:

1. `beacon.sink(task=...)` → sends a `▶ STARTED` sentinel to the server.
2. With `heartbeat=10` → a `__TASK_HEARTBEAT__` is sent every 10s (hidden
   from the log view). If heartbeats stop, the task shows as `disconnected`
   within ~30s.
3. Script exits normally → `atexit` sends a `⬥ DISCONNECTED ⬥` sentinel.
4. `beacon.mark_done(task="...")` → sends a `⬥ COMPLETED ⬥` sentinel.
5. No activity for 30min → `disconnected`.

```python
# Manual mark (explicit, same as clicking "Mark done" in the UI)
beacon.mark_done(task="training_a")
```

If you do not want the dependency, point any HTTP client at `POST /api/log`
directly:

```bash
curl -X POST http://your-server:8000/api/log \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"task":"training_a","level":"INFO","message":"hello"}'
```

## CLI

`beacon` is a single-command Typer app; everything is on one screen.

```bash
uv run beacon -h
```

| Option              | Default              | Notes                                                          |
| ------------------- | -------------------- | -------------------------------------------------------------- |
| `--host`            | `0.0.0.0`            | Bind address. Default lets the LAN reach you.                  |
| `--port`, `-p`      | `8000`               |                                                                |
| `--reload`          | off                  | Dev auto-reload (forces single worker).                        |
| `--token`           | _from env_           | Falls back to `BEACON_API_TOKEN`, then `data/beacon.token`.    |
| `--admin-password`  | _from env_           | Admin password for Web UI login. Falls back to `BEACON_ADMIN_PASSWORD`, then auto-generated. |
| `--no-auth`         | off                  | Disables bearer auth entirely. Local trusted networks only.    |
| `--db`              | `data/beacon.db`     | SQLite path. Also via `BEACON_SQLITE_PATH`.                    |
| `--running-window-s`| `1800` (30min)       | Seconds without logs before a task is `disconnected`.          |
| `--workers`         | `1`                  | Keep at 1 unless you front it with shared storage.             |
| `--version`, `-V`   |                      | Prints the installed version.                                  |

A few common combinations:

```bash
uv run beacon                                  # auto-token, prints it on stdout
uv run beacon --reload                         # dev mode
uv run beacon --no-auth                        # no auth, for trusted LAN only
uv run beacon --port 9000 --db /var/beacon.db  # custom path and port
```

`beacon-demo` is the smoke-test counterpart:

```bash
uv run beacon-demo                             # default task=demo_task, 1s/line, forever
uv run beacon-demo training_a -i 0.3 -n 50     # 50 log lines, 0.3s apart
uv run beacon-demo crawler -m "started" -L INFO   # one explicit message
uv run beacon-demo --url http://192.168.1.10:8000 my_task   # remote server
uv run beacon-demo done training_a                           # mark a task as done
```

## API

### Authentication

Endpoints under `/api` (except `/api/auth/login`) require one of:

- `Authorization: Bearer <static_token>` — used by automated scripts and
  sinks. The token is auto-generated on first start and persisted to
  `data/beacon.token`.
- `Authorization: Bearer <JWT>` — obtained from `POST /api/auth/login`
  with the admin password. Used by the browser UI. JWT expires after
  7 days.

If the server is started with `--no-auth`, all endpoints are open.

### `POST /api/auth/login`

Authenticate with the admin password and receive a JWT.

```json
// request
{ "password": "admin-password" }
// response
{ "access_token": "eyJ...", "token_type": "bearer" }
```

### `POST /api/log`

```json
{
  "task": "training_a",
  "level": "INFO",
  "message": "step=123 loss=0.21",
  "timestamp": "2026-05-09T12:00:00",
  "host": "desktop-a"
}
```

`timestamp` and `host` are optional (server fills them in). Returns `{"ok": true}`.

`GET /api/tasks` returns one summary per task with the inferred status:

```json
[
  {
    "task": "training_a",
    "status": "running",
    "last_seen": "2026-05-09T12:00:00Z",
    "last_level": "INFO",
    "last_message": "step=123 loss=0.21",
    "last_id": 1234
  }
]
```

`GET /api/logs/{task}?after_id=N&limit=500` returns log lines with
`id > N` in ascending order. The dashboard polls this every second to
append new lines without re-fetching the page.

`DELETE /api/tasks/{task}?force=false` removes **every** stored log line for
that task name (there is no separate tasks table). Returns `{"ok": true, "deleted": N}`.
If the inferred status is `running` and `force` is false, responds with **409**
so you do not wipe a task that is still receiving logs by accident; retry with
`?force=true`. Unknown tasks return **404**.

`DELETE /api/tasks` removes logs for **all finished tasks** (disconnected)
in one shot. Returns `{"ok": true, "deleted_tasks": T, "deleted_rows": R}`
where `T` is the number of task names removed and `R` is total deleted log
rows.

### `POST /api/sys-stats`

Record a system stats snapshot for a task.

```json
{
  "task": "training_a",
  "cpu_percent": 45.2,
  "memory_percent": 62.8,
  "memory_used_mb": 8192,
  "memory_total_mb": 16384,
  "gpu_percent": 78.0,
  "gpu_memory_percent": 35.5,
  "gpu_memory_used_mb": 4096,
  "gpu_memory_total_mb": 8192,
  "load_1m": 1.5,
  "load_5m": 1.2,
  "load_15m": 0.9,
  "collection_interval": 10.0
}
```

All fields except `task` are optional. Returns `{"ok": true}`.

### `GET /api/sys-stats/{task}`

Returns the latest snapshot for a task, with a computed `fresh` boolean:

```json
{
  "id": 1,
  "task_name": "training_a",
  "source_host": "desktop-a",
  "timestamp": "2026-05-17T12:00:00Z",
  "collection_interval": 10.0,
  "cpu_percent": 45.2,
  "memory_percent": 62.8,
  "memory_used_mb": 8192.0,
  "memory_total_mb": 16384.0,
  "gpu_percent": 78.0,
  "gpu_memory_percent": 35.5,
  "gpu_memory_used_mb": 4096.0,
  "gpu_memory_total_mb": 8192.0,
  "load_1m": 1.5,
  "load_5m": 1.2,
  "load_15m": 0.9,
  "fresh": true
}
```

`fresh=false` when the data is older than `3 × collection_interval`.

### `POST /api/tasks/{task}/done`

Marks a task as finished by inserting a
`__TASK_DONE__` sentinel entry. The task immediately shows as `disconnected`
on the dashboard, regardless of the time window. If the script runs again
and sends new logs, the sentinel is overridden and the task returns to
`running` automatically.

```bash
curl -X POST "http://your-server:8000/api/tasks/training_a/done" \
  -H "Authorization: Bearer $TOKEN"
```

From curl:

```bash
curl -X DELETE "http://your-server:8000/api/tasks/training_a" \
  -H "Authorization: Bearer $TOKEN"
```

All knobs are environment variables; the CLI flags above just write into
this same set so flags and env behave identically.

| Variable                  | Default            | Purpose                                                       |
| ------------------------- | ------------------ | ------------------------------------------------------------- |
| `BEACON_API_TOKEN`        | _(auto-generated)_ | Shared bearer token. Empty string disables auth.              |
| `BEACON_ADMIN_PASSWORD`   | _(auto-generated)_ | Admin password used by the Web UI login to obtain a JWT.      |
| `BEACON_SQLITE_PATH`      | `data/beacon.db`   | Where to put the SQLite file.                                 |
| `BEACON_RUNNING_WINDOW_S` | `1800` (30min)     | Seconds without logs before a task is considered `disconnected`. |
| `BEACON_STATS_TIMEOUT_MULTIPLIER` | `3` | Multiplier applied to `collection_interval` to determine staleness. |

A starter `.env.example` is checked in; copy to `.env` for compose use.

## Deployment

For a single-host deploy, Docker Compose is the path of least resistance:

```bash
cp .env.example .env       # set BEACON_API_TOKEN
docker compose up --build -d
```

Behind a public domain, put it behind [Caddy](https://caddyserver.com/)
or any other reverse proxy that handles HTTPS for you; Beacon itself only
speaks plain HTTP and trusts whoever can present the bearer token.

If you don't have Docker, `uv run beacon --port 8000` under a `systemd`
unit or `tmux` works equally well; the SQLite file in `data/` is the only
persistent state.

## UI features

- Live indicator dot in the header reacts to HTMX request success / failure
  so you can tell at a glance whether the panel is actually fresh.
- Detail page has level filter chips, a substring search, multi-line
  traceback folding (`+N lines` summary), auto-follow with a "▼ N new"
  badge when scrolled up, and breadcrumb navigation.
- Tailwind CDN + Inter / JetBrains Mono with CJK system fallbacks
  (PingFang SC, Microsoft Yahei, Source Han Sans) so Chinese log lines render
  cleanly on macOS / Windows / Linux without extra downloads.
- Task list and detail page include **Clear / delete** controls. When you
  click delete and are not yet authenticated, a **login modal** appears.
  Enter the admin password printed at startup; the server returns a JWT
  stored in `localStorage` (survives browser restarts).
- Task cards show a colored status badge (dot + label) for `Running`,
  `Error`, and `Disconnected` (finished).
- Sentinel entries (`▶ STARTED`, `⬥ COMPLETED ⬥`, `⬥ DISCONNECTED ⬥`)
  are rendered as centered separator lines, visually distinct from logs.
- Each log line has a **level-colored left bar** for quick scanning on
  mobile; the search bar on the task list page lets you filter by task name.

## Skill for code agents

If you let coding agents (Claude Code, OpenCode, etc.) work on
the projects you want monitored, drop
[`skills/beacon-logging/SKILL.md`](./skills/beacon-logging/SKILL.md)
into that project's skills directory. The agent then knows when to
suggest Beacon, which env vars to ask for, how to wire Loguru / stdlib
`logging` / curl, and which conventions to follow.

## Layout

```text
src/beacon/
├── api/             # FastAPI routes + auth dependency
├── client/          # BeaconClient + beacon-demo CLI (the `client` extra)
├── database/        # SQLite engine + session
├── models/          # SQLModel LogEntry + SystemSnapshot
├── services/        # task aggregation, status + system stats logic
├── templates/       # Jinja2 + favicon.svg
├── cli.py           # `beacon` console script
├── config.py        # env-driven Settings
└── main.py          # FastAPI app + HTML routes
```

## Roadmap

Not done yet, in rough priority order:

- websocket push (drop the 1s polling)
- task heartbeat / last-restart metadata
- traceback dedupe and per-error pages
- full-text search and tag filters
- Telegram / ntfy push for `ERROR` events
- PWA install banner

## License

MIT.
