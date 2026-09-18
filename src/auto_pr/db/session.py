"""Database connection and session factory management (SQLAlchemy 2.0 Async)."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from auto_pr.config import settings


class Base(DeclarativeBase):
    """SQLAlchemy Declarative Base."""
    pass


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine(db_url: str | None = None) -> AsyncEngine:
    """Get or create the singleton async database engine."""
    global _engine, _sessionmaker
    url = db_url or settings.database_url
    if _engine is None or str(_engine.url) != url:
        _engine = create_async_engine(
            url,
            echo=settings.db_echo,
            future=True,
        )
        _sessionmaker = async_sessionmaker(
            bind=_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _engine


def get_sessionmaker(db_url: str | None = None) -> async_sessionmaker[AsyncSession]:
    """Get or create the session factory."""
    global _sessionmaker
    if _sessionmaker is None:
        get_engine(db_url)
    assert _sessionmaker is not None
    return _sessionmaker


@asynccontextmanager
async def get_session(db_url: str | None = None) -> AsyncGenerator[AsyncSession, None]:
    """Async context manager providing a scoped database session."""
    session_factory = get_sessionmaker(db_url)
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db(db_url: str | None = None) -> None:
    """Create all tables in the database (used in setup and testing)."""
    engine = get_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Dispose the database engine."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None
