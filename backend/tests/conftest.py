from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db

TEST_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/alt_fast_test"

_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
_session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


def _create_test_app() -> FastAPI:
    """프로덕션 lifespan 없이 테스트용 앱 생성."""
    from app.api.router import router

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        yield

    test_app = FastAPI(lifespan=_lifespan)
    test_app.include_router(router)

    from fastapi.middleware.cors import CORSMiddleware
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return test_app


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _setup_tables():
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def db(_setup_tables) -> AsyncGenerator[AsyncSession, None]:
    session = _session_factory()
    try:
        yield session
    finally:
        await session.close()

    async with _engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


@pytest_asyncio.fixture(loop_scope="session")
async def client(_setup_tables) -> AsyncGenerator[AsyncClient, None]:
    test_app = _create_test_app()

    async def _override_get_db():
        async with _session_factory() as session:
            yield session

    test_app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    test_app.dependency_overrides.clear()
