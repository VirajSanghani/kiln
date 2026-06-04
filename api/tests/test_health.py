"""Phase 0 smoke test: proves the FastAPI app boots and the test harness is wired.

Liveness is hermetic (no DB needed). Readiness is exercised end-to-end against the
real Postgres in docker-compose, not here.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_liveness_ok():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "kiln-api"


def test_root_points_to_health():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["health"] == "/api/health"
