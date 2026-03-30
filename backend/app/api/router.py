from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.chart import router as chart_router
from app.api.chatbot import router as chatbot_router
from app.api.deploy import router as deploy_router
from app.api.event_trader import router as event_trader_router
from app.api.dashboard import router as dashboard_router
from app.api.macro import router as macro_router
from app.api.news import router as news_router
from app.api.report import router as report_router
from app.api.settings import router as settings_router
from app.api.strategies import router as strategies_router
from app.api.trades import router as trades_router

router = APIRouter()


@router.get("/api/health")
async def health_check():
    return {"status": "ok"}


router.include_router(auth_router)
router.include_router(chart_router)
router.include_router(chatbot_router)
router.include_router(dashboard_router)
router.include_router(macro_router)
router.include_router(strategies_router)
router.include_router(trades_router)
router.include_router(news_router)
router.include_router(report_router)
router.include_router(settings_router)
router.include_router(deploy_router)
router.include_router(event_trader_router)
