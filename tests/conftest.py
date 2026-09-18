"""Shared test fixtures for Auto PR Control Plane."""

from collections.abc import AsyncGenerator
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from auto_pr.db.session import Base
from auto_pr.db.repository import WorkflowRepository
from auto_pr.security.redaction import clear_registered_secrets


@pytest.fixture(autouse=True)
def clean_registered_secrets() -> None:
    """Clear any dynamically registered secrets before each test."""
    clear_registered_secrets()


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an isolated, in-memory SQLite database session for unit tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def repo(db_session: AsyncSession) -> WorkflowRepository:
    """Provide a WorkflowRepository bound to the test database session."""
    return WorkflowRepository(db_session)
