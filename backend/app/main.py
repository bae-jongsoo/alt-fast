from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.router import router
from app.database import async_session, engine
from app.services.settings import seed_default_parameters


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: DB 연결 확인
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        print("Database connection established.")
        # 시스템 파라미터 기본값 시딩
        async with async_session() as session:
            await seed_default_parameters(session)
        print("Default system parameters seeded.")
    except Exception as e:
        print(f"Database connection failed: {e}")

    yield

    # Shutdown
    await engine.dispose()


app = FastAPI(title="ALT-Web", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
