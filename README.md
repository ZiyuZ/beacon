<!-- markdownlint-disable MD013 MD033 MD041 -->
<p align="right">
  English | <a href="./README.zh-CN.md">简体中文</a>
</p>

# Beacon

A lightweight personal log dashboard. Your scripts push logs over HTTP, you
watch them live from a phone or laptop. SQLite + FastAPI + HTMX, no agents,
no observability stack to babysit.

![Status](https://img.shields.io/badge/status-alpha-orange)
![Python](https://img.shields.io/badge/python-3.13%2B-blue)

## What it is

- **Server** (`beacon`): FastAPI app with three JSON endpoints and a small
  HTMX UI; data lives in a single SQLite file.
- **Client** (`beacon.client.remote_sink`): a Loguru sink that ships records
  to the server, plus a `beacon-demo` CLI that streams fake logs for testing.
- **Status inference**: a task is `running` if it produced a log in the
  last 30s, `error` if its most recent log is `ERROR`/`CRITICAL`, otherwise
  `inactive`. No heartbeats to wire up.

What it is not: an ELK/Loki replacement, a multi-user system, an SSH
terminal. It is a personal panel for a handful of long-running scripts.

## Quick start

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/ZiyuZ/beacon.git
cd beacon
uv sync
uv run beacon
```

On first start the server prints a generated bearer token and the SQLite
path it picked, then listens on `0.0.0.0:8000`:

```text
Beacon listening on http://0.0.0.0:8000
  bearer token: NSxxxxxxxxxxxxxxxxxxxxxxxxxxxx
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

## Sending real logs from your scripts

Add Beacon to whichever project does the logging. You have two practical options:

```bash
# from git, with the optional `client` extra (loguru):
uv add "beacon[client] @ git+https://github.com/ZiyuZ/beacon.git"

# or, if you already have the repo cloned locally:
uv add --editable "../beacon[client]"
```

Then add the sink to your existing Loguru setup:

```python
from loguru import logger
from beacon.client.remote_sink import remote_sink

logger.add(
    remote_sink(
        url="http://your-server:8000",
        task="training_a",
        token="NSxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    ),
    enqueue=True,       # never block the hot path
    backtrace=False,
    diagnose=False,
)

logger.info("started")
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
| `--no-auth`         | off                  | Disables bearer auth entirely. Local trusted networks only.    |
| `--db`              | `data/beacon.db`     | SQLite path. Also via `BEACON_SQLITE_PATH`.                    |
| `--running-window-s`| `30`                 | Seconds without logs before a task is `inactive`.              |
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
```

## API

Three routes under `/api`. All require `Authorization: Bearer <token>`
unless the server was started with `--no-auth`.

`POST /api/log` ingests one log line.

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

## Configuration

All knobs are environment variables; the CLI flags above just write into
this same set so flags and env behave identically.

| Variable                  | Default            | Purpose                                                       |
| ------------------------- | ------------------ | ------------------------------------------------------------- |
| `BEACON_API_TOKEN`        | _(auto-generated)_ | Shared bearer token. Empty string disables auth.              |
| `BEACON_SQLITE_PATH`      | `data/beacon.db`   | Where to put the SQLite file.                                 |
| `BEACON_RUNNING_WINDOW_S` | `30`               | Seconds without logs before a task is considered `inactive`.  |

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
- Mobile-first single-column layout with a custom thin scrollbar.

## Layout

```text
src/beacon/
├── api/             # FastAPI routes + auth dependency
├── client/          # remote_sink + beacon-demo CLI (the `client` extra)
├── database/        # SQLite engine + session
├── models/          # SQLModel LogEntry
├── services/        # task aggregation and status logic
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
