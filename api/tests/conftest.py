"""Test fixtures.

Tests use an in-memory SQLite database created with create_all — that is the TEST
harness, deliberately separate from the production migration path (Postgres + Alembic).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def api():
    """TestClient wired to an in-memory DB, with seeded operator + two requesters and a
    login helper. Returns a namespace: .client .db .login(username,pw)->headers .op .rq .rq2"""
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from app.deps import get_db
    from app.enums import UserRole
    from app.main import app
    from app.models import User
    from app.security import hash_password

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    db = Session()

    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    op = User(username="op", display_name="Op", role=UserRole.operator, password_hash=hash_password("op-pw"))
    rq = User(username="rq", display_name="Rq", role=UserRole.requester, password_hash=hash_password("rq-pw"))
    rq2 = User(username="rq2", display_name="Rq2", role=UserRole.requester, password_hash=hash_password("rq2-pw"))
    db.add_all([op, rq, rq2])
    db.commit()

    def login(username, pw):
        r = client.post("/api/auth/login", json={"username": username, "password": pw})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    try:
        yield SimpleNamespace(client=client, db=db, login=login, op=op, rq=rq, rq2=rq2)
    finally:
        app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(engine)
