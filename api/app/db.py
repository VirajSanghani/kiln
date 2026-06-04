"""Database engine + session factory.

Phase 0 only exposes a connectivity probe used by the readiness endpoint. Models and
the real session lifecycle land in Phase 1. We do NOT fake the DB status — check_db()
runs an actual round-trip and the readiness endpoint reports the truth.
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from .config import settings

# pool_pre_ping avoids handing out dead connections after a db restart.
engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def check_db() -> bool:
    """Return True iff a real SELECT 1 round-trip to the database succeeds."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
