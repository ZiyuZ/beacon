"""Runtime configuration sourced from environment variables."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    api_token: str
    admin_password: str
    sqlite_path: Path
    running_window_seconds: int
    stats_timeout_multiplier: int

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.sqlite_path.as_posix()}"


def load_settings() -> Settings:
    sqlite_path = Path(os.environ.get("BEACON_SQLITE_PATH", "data/beacon.db")).resolve()
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    return Settings(
        api_token=os.environ.get("BEACON_API_TOKEN", ""),
        admin_password=os.environ.get("BEACON_ADMIN_PASSWORD", ""),
        sqlite_path=sqlite_path,
        running_window_seconds=int(os.environ.get("BEACON_RUNNING_WINDOW_S", "1800")),
        stats_timeout_multiplier=int(
            os.environ.get("BEACON_STATS_TIMEOUT_MULTIPLIER", "3")
        ),
    )
