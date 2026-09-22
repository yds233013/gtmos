from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from tests.conftest import TEST_DB

pytestmark = pytest.mark.db


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    from gtmos.config import get_settings
    from gtmos.models import Base

    get_settings.cache_clear()
    eng = create_engine(TEST_DB, future=True)
    try:
        with eng.connect() as c:
            c.execute(text("select 1"))
    except OperationalError:
        pytest.skip(f"PostgreSQL not reachable at {TEST_DB} (run `make dev-deps`)")
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    from gtmos.seed.generator import seed

    with Session(eng) as s:
        seed(s, size=150, execute_live_workflows=3)
        s.commit()
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        conn.close()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    from gtmos.api.deps import db_session
    from gtmos.main import app

    def override() -> Iterator[Session]:
        yield db

    app.dependency_overrides[db_session] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def ws(db: Session):  # type: ignore[no-untyped-def]
    from gtmos.services.common import get_workspace

    return get_workspace(db)


@pytest.fixture
def flagship(db: Session, ws):  # type: ignore[no-untyped-def]
    from sqlalchemy import select

    from gtmos.models import Account

    return db.scalars(select(Account).where(Account.workspace_id == ws.id, Account.is_flagship.is_(True))).one()
