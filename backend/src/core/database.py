from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from src.core.config import get_settings

settings = get_settings()

if settings.database_url:
    engine_kwargs: dict[str, object] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
    if settings.database_url.startswith(("postgresql://", "postgresql+", "postgres://")):
        engine_kwargs["connect_args"] = {"connect_timeout": 5}
    engine = create_engine(settings.database_url, **engine_kwargs)
else:
    engine = None

SessionLocal = (
    sessionmaker(autocommit=False, autoflush=False, bind=engine) if engine else None
)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    if SessionLocal is None:
        raise RuntimeError("Database is not configured.")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
