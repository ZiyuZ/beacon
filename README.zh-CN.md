<!-- markdownlint-disable MD013 MD033 MD041 -->
<p align="right">
  <a href="./README.md">English</a> | 简体中文
</p>

# Beacon

轻量级个人日志面板：脚本通过 HTTP 上报日志，在手机或浏览器里实时查看。SQLite + FastAPI + HTMX，无需 agent，也不用维护一整套可观测性栈。

![Status](https://img.shields.io/badge/status-alpha-orange)
![Python](https://img.shields.io/badge/python-3.13%2B-blue)

## 这是什么

- **服务端**（`beacon`）：FastAPI，三个 JSON 接口 + HTMX 小界面；数据存在单个 SQLite 文件里。
- **客户端**（`beacon.client.remote_sink`）：Loguru 远端 sink，把日志发到服务端；另有 `beacon-demo` 命令行用于测试日志。
- **任务状态**：最近 30 秒内有日志则为 `running`；最近一条是 `ERROR`/`CRITICAL` 则为 `error`；否则 `inactive`。无需单独的心跳接口。

这不是 ELK/Loki 替代品，也不是多用户平台或 SSH 终端——只适合少量常驻脚本的个人监控面板。

## 快速开始

需要 Python 3.13+ 与 [uv](https://docs.astral.sh/uv/)。

```bash
git clone https://github.com/ZiyuZ/beacon.git
cd beacon
uv sync
uv run beacon
```

首次启动会在终端打印自动生成的 Bearer Token 与 SQLite 路径，并在 `0.0.0.0:8000` 监听：

```text
Beacon listening on http://0.0.0.0:8000
  bearer token: NSxxxxxxxxxxxxxxxxxxxxxxxxxxxx
  sqlite: /app/beacon/data/beacon.db
```

Token 会写入 `data/beacon.token`，重启后保持不变。用手机在同一局域网访问打印出的地址即可打开空白仪表盘（`0.0.0.0` 绑定便于局域网访问）。

另开一个终端灌几条假日志，做一次端到端验证：

```bash
uv run beacon-demo training_a -i 0.5
```

`beacon-demo` 会读取同目录下的 `data/beacon.token`，本地调试一般无需手动复制 Token。

## 在脚本里上报真实日志

把 Beacon 加到你的日志工程里。在包尚未发布到 PyPI 之前，常用两种方式：

```bash
# 从 Git 安装，并带上可选 extra `client`（内含 loguru）：
uv add "beacon[client] @ git+https://github.com/ZiyuZ/beacon.git"

# 或者本地已有克隆时，使用可编辑安装：
uv add --editable "../beacon[client]"
```

然后在现有 Loguru 配置里挂上 sink：

```python
from loguru import logger
from beacon.client.remote_sink import remote_sink

logger.add(
    remote_sink(
        url="http://your-server:8000",
        task="training_a",
        token="NSxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    ),
    enqueue=True,       # 不阻塞主线程
    backtrace=False,
    diagnose=False,
)

logger.info("started")
```

如果不想引入依赖，任意 HTTP 客户端直接调用 `POST /api/log` 即可：

```bash
curl -X POST http://your-server:8000/api/log \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"task":"training_a","level":"INFO","message":"hello"}'
```

## 命令行

`beacon` 是 Typer 单命令入口，所有选项在同一屏帮助里：

```bash
uv run beacon -h
```

| 选项 | 默认值 | 说明 |
| --- | --- | --- |
| `--host` | `0.0.0.0` | 监听地址；默认允许局域网访问 |
| `--port`，`-p` | `8000` | 端口 |
| `--reload` | 关闭 | 开发热重载（强制单 worker） |
| `--token` | 见下方 | 依次读取 `--token` → `BEACON_API_TOKEN` → `data/beacon.token` |
| `--no-auth` | 关闭 | 关闭鉴权，仅限可信内网 |
| `--db` | `data/beacon.db` | SQLite 路径，亦可设 `BEACON_SQLITE_PATH` |
| `--running-window-s` | `30` | 多少秒无新日志视为 `inactive` |
| `--workers` | `1` | 除非前置共享存储，否则保持 1 |
| `--version`，`-V` | | 打印版本号 |

常用组合：

```bash
uv run beacon                                  # 自动生成 token 并打印
uv run beacon --reload                         # 开发模式
uv run beacon --no-auth                        # 无鉴权（仅可信局域网）
uv run beacon --port 9000 --db /var/beacon.db  # 自定义端口与数据库路径
```

`beacon-demo` 用于冒烟测试：

```bash
uv run beacon-demo                             # 默认任务 demo_task，每秒一行，持续运行
uv run beacon-demo training_a -i 0.3 -n 50   # 共 50 行，间隔 0.3 秒
uv run beacon-demo crawler -m "started" -L INFO   # 单行自定义消息
uv run beacon-demo --url http://192.168.1.10:8000 my_task   # 指向远端服务
```

## API

`/api` 下三条路由。除非启动时带了 `--no-auth`，否则均需 `Authorization: Bearer <token>`。

`POST /api/log` 写入一条日志：

```json
{
  "task": "training_a",
  "level": "INFO",
  "message": "step=123 loss=0.21",
  "timestamp": "2026-05-09T12:00:00",
  "host": "desktop-a"
}
```

`timestamp` 与 `host` 可选（服务端可补全）。返回 `{"ok": true}`。

`GET /api/tasks` 返回每个任务的摘要及推断状态：

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

`GET /api/logs/{task}?after_id=N&limit=500` 返回 `id > N` 的日志，按 id 升序。仪表盘每秒轮询该接口增量追加，无需整页刷新。

## 配置

环境变量与 CLI 参数一一对应（CLI 会把选项写入同一套环境变量）。

| 变量 | 默认值 | 含义 |
| --- | --- | --- |
| `BEACON_API_TOKEN` | （首次自动生成） | 共享 Bearer Token；设为空字符串则关闭鉴权 |
| `BEACON_SQLITE_PATH` | `data/beacon.db` | SQLite 文件路径 |
| `BEACON_RUNNING_WINDOW_S` | `30` | 多少秒无日志视为 `inactive` |

仓库内置 `.env.example`，配合 Compose 时可复制为 `.env`。

## 部署

单机部署最简单是用 Docker Compose：

```bash
cp .env.example .env       # 填写 BEACON_API_TOKEN
docker compose up --build -d
```

若暴露在公网域名下，建议前面挂 [Caddy](https://caddyserver.com/) 或其它反向代理做 HTTPS；Beacon 本身只处理明文 HTTP，鉴权依赖 Bearer Token。

没有 Docker 时，用 `systemd`、`tmux` 或直接 `uv run beacon --port 8000` 均可；持久化数据只有 `data/` 下的 SQLite。

## 界面特性

- 顶栏圆点随 HTMX 请求成功/失败变色，一眼看出面板是否在刷新。
- 详情页支持按级别筛选、消息子串搜索、多行堆栈折叠（`+N lines`）、向上滚动暂停后底部「▼ N 条新日志」提示、面包屑导航。
- Tailwind CDN + Inter / JetBrains Mono，中文回退到系统字体（苹方、微软雅黑、思源黑体等），无需额外下载字体包。
- 移动端单列布局，自定义细滚动条。

## 目录结构

```text
src/beacon/
├── api/             # FastAPI 路由与鉴权依赖
├── client/          # remote_sink 与 beacon-demo（可选 extra `client`）
├── database/        # SQLite 引擎与会话
├── models/          # SQLModel LogEntry
├── services/        # 任务聚合与状态推断
├── templates/       # Jinja2 模板与 favicon.svg
├── cli.py           # `beacon` 入口
├── config.py        # 环境变量配置
└── main.py          # FastAPI 应用与 HTML 路由
```

## 路线图

尚未实现，大致优先级如下：

- WebSocket 推送（替代每秒轮询）
- 任务心跳 / 上次重启时间等元数据
- 堆栈去重与独立错误页
- 全文检索与标签过滤
- Telegram / ntfy 在 `ERROR` 时推送
- PWA 安装提示

## 许可证

MIT。
