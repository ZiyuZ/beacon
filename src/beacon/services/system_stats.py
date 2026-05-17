"""System snapshot — save & query helpers."""

from datetime import datetime, timezone

from sqlalchemy import func
from sqlmodel import Session, select, col

from beacon.models.system_snapshot import SystemSnapshot, SystemSnapshotRead

# Default multiplier: data is considered stale when its age exceeds
# collection_interval × STALE_MULTIPLIER.
STALE_MULTIPLIER = 3


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _inject_fresh(
    snapshot: SystemSnapshot,
    now: datetime | None = None,
    multiplier: int = STALE_MULTIPLIER,
) -> SystemSnapshotRead:
    """Convert a DB row to a read schema with a computed ``fresh`` flag."""
    now = now or _now()
    age = (now - _ensure_aware(snapshot.timestamp)).total_seconds()
    fresh = age <= multiplier * snapshot.collection_interval
    return SystemSnapshotRead(
        id=snapshot.id or 0,
        task_name=snapshot.task_name,
        source_host=snapshot.source_host,
        timestamp=snapshot.timestamp,
        collection_interval=snapshot.collection_interval,
        cpu_percent=snapshot.cpu_percent,
        memory_percent=snapshot.memory_percent,
        memory_used_mb=snapshot.memory_used_mb,
        memory_total_mb=snapshot.memory_total_mb,
        gpu_percent=snapshot.gpu_percent,
        gpu_memory_percent=snapshot.gpu_memory_percent,
        gpu_memory_used_mb=snapshot.gpu_memory_used_mb,
        gpu_memory_total_mb=snapshot.gpu_memory_total_mb,
        load_1m=snapshot.load_1m,
        load_5m=snapshot.load_5m,
        load_15m=snapshot.load_15m,
        fresh=fresh,
    )


def save_snapshot(
    session: Session,
    task: str,
    host: str | None,
    interval: float,
    stats: dict,
) -> SystemSnapshot:
    """Persist a ``SystemSnapshot`` row and return it."""
    entry = SystemSnapshot(
        task_name=task,
        source_host=host,
        timestamp=stats.get("timestamp") or _now(),
        collection_interval=interval,
        cpu_percent=stats.get("cpu_percent"),
        memory_percent=stats.get("memory_percent"),
        memory_used_mb=stats.get("memory_used_mb"),
        memory_total_mb=stats.get("memory_total_mb"),
        gpu_percent=stats.get("gpu_percent"),
        gpu_memory_percent=stats.get("gpu_memory_percent"),
        gpu_memory_used_mb=stats.get("gpu_memory_used_mb"),
        gpu_memory_total_mb=stats.get("gpu_memory_total_mb"),
        load_1m=stats.get("load_1m"),
        load_5m=stats.get("load_5m"),
        load_15m=stats.get("load_15m"),
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def get_latest_snapshot(
    session: Session,
    task: str,
    *,
    now: datetime | None = None,
    multiplier: int = STALE_MULTIPLIER,
) -> SystemSnapshotRead | None:
    """Return the most recent snapshot for *task*, or ``None``."""
    stmt = (
        select(SystemSnapshot)
        .where(col(SystemSnapshot.task_name) == task)
        .order_by(col(SystemSnapshot.id).desc())
        .limit(1)
    )
    row = session.exec(stmt).first()
    if row is None:
        return None
    return _inject_fresh(row, now=now, multiplier=multiplier)


def get_latest_snapshots_for_tasks(
    session: Session,
    tasks: list[str],
    *,
    now: datetime | None = None,
    multiplier: int = STALE_MULTIPLIER,
) -> dict[str, SystemSnapshotRead]:
    """Batch-fetch the latest snapshot per task.

    Returns a dict keyed by task name.  Tasks without any snapshot are
    omitted so callers can distinguish "never had stats" from "stale".
    """
    if not tasks:
        return {}

    # Subquery: latest id per task_name.
    latest_id_subq = (
        select(
            SystemSnapshot.task_name,
            func.max(SystemSnapshot.id).label("max_id"),
        )
        .where(col(SystemSnapshot.task_name).in_(tasks))
        .group_by(SystemSnapshot.task_name)
        .subquery()
    )

    stmt = select(SystemSnapshot).join(
        latest_id_subq, col(SystemSnapshot.id) == latest_id_subq.c.max_id
    )
    rows = session.exec(stmt).all()

    result: dict[str, SystemSnapshotRead] = {}
    for row in rows:
        result[row.task_name] = _inject_fresh(row, now=now, multiplier=multiplier)
    return result
