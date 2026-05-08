"""Runtime configuration sourced from environment variables."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    api_token: str
    sqlite_path: Path
    running_window_seconds: int

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.sqlite_path.as_posix()}"


def load_settings() -> Settings:
    sqlite_path = Path(os.environ.get("BEACON_SQLITE_PATH", "data/beacon.db")).resolve()
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    return Settings(
        api_token=os.environ.get("BEACON_API_TOKEN", ""),
        sqlite_path=sqlite_path,
        running_window_seconds=int(os.environ.get("BEACON_RUNNING_WINDOW_S", "30")),
    )
