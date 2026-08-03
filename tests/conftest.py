from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.database import create_sqlite_engine
from app.models import Base


@pytest.fixture()
def session_factory(tmp_path) -> Iterator[sessionmaker[Session]]:
    engine = create_sqlite_engine(tmp_path / "test.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    yield factory
    engine.dispose()


@pytest.fixture()
def db_session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as session:
        yield session

