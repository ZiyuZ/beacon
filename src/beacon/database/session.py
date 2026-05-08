"""SQLite engine and session helpers."""

from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from beacon.config import load_settings

_settings = load_settings()

# `check_same_thread=False` is required because FastAPI may dispatch the same
# session across threads when using sync endpoints with a thread pool.
engine = create_engine(
    _settings.database_url,
    connect_args={"check_same_thread": False},
)


def create_db_and_tables() -> None:
    # Importing here avoids a circular import at module load time.
    from beacon.models import log_entry  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
