"""Health endpoints.

- GET /api/health         liveness: the app is up and serving. Always 200.
- GET /api/health/ready   readiness: reports REAL database connectivity. 503 if the
                          DB is unreachable. The `db` field is honest, never faked.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Response, status

from ..config import settings
from ..db import check_db

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
def liveness():
    return {
        "status": "ok",
        "service": settings.service_name,
        "version": settings.version,
    }


@router.get("/ready")
def readiness(response: Response):
    db_ok = check_db()
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if db_ok else "degraded",
        "service": settings.service_name,
        "version": settings.version,
        "db": "connected" if db_ok else "unreachable",
        "time": datetime.now(timezone.utc).isoformat(),
    }
