from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import Settings


class Base(DeclarativeBase):
    pass


engine = create_engine(Settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def lock_performance_writes(session: Session) -> None:
    """Serialize seed and import writers until the transaction ends."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(417240031)"))
