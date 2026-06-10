from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import BigInteger, Integer, MetaData, event, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from src.config import Settings, get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

BIGINT_PK = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    """Base class for declarative SQLAlchemy models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _resolve_settings(settings: Settings | None = None) -> Settings:
    return settings or get_settings()


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    """Return a lazily created async SQLAlchemy engine."""
    global _engine
    resolved_settings = _resolve_settings(settings)
    if _engine is None:
        _engine = create_async_engine(
            resolved_settings.database_url,
            future=True,
            pool_pre_ping=True,
        )
        if make_database_url(resolved_settings).drivername.startswith("sqlite"):
            _configure_sqlite_pragmas(_engine)
    return _engine


def get_session_factory(
    settings: Settings | None = None,
) -> async_sessionmaker[AsyncSession]:
    """Return a lazily created async session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(settings),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


def make_database_url(settings: Settings | None = None) -> URL:
    """Return the configured database URL as a SQLAlchemy URL object."""
    return make_url(_resolve_settings(settings).database_url)


@asynccontextmanager
async def session_scope(
    settings: Settings | None = None,
) -> AsyncIterator[AsyncSession]:
    """Yield an async database session."""
    session_factory = get_session_factory(settings)
    async with session_factory() as session:
        yield session


def _configure_sqlite_pragmas(engine: AsyncEngine) -> None:
    """Attach SQLite pragmas that make the single-process bot more resilient."""

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


async def get_sqlite_runtime_pragmas(
    settings: Settings | None = None,
) -> dict[str, str] | None:
    """Return key SQLite runtime pragma values for diagnostics."""
    engine = get_engine(settings)
    if not make_database_url(settings).drivername.startswith("sqlite"):
        return None
    async with engine.connect() as connection:
        journal_mode = (await connection.execute(text("PRAGMA journal_mode"))).scalar() or ""
        busy_timeout = (await connection.execute(text("PRAGMA busy_timeout"))).scalar() or ""
        foreign_keys = (await connection.execute(text("PRAGMA foreign_keys"))).scalar() or ""
        synchronous = (await connection.execute(text("PRAGMA synchronous"))).scalar() or ""
    return {
        "journal_mode": str(journal_mode),
        "busy_timeout": str(busy_timeout),
        "foreign_keys": str(foreign_keys),
        "synchronous": str(synchronous),
    }
