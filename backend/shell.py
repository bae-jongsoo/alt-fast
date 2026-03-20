"""
FastAPI async shell - Django shell 대용

사용법: .venv/bin/ipython -i shell.py
"""
import asyncio

from app.database import async_session
from app.models.asset import Asset
from app.models.dart_disclosure import DartDisclosure
from app.models.decision_history import DecisionHistory
from app.models.market_snapshot import MarketSnapshot
from app.models.minute_candle import MinuteCandle
from app.models.news import News
from app.models.order_history import OrderHistory
from app.models.prompt_template import PromptTemplate
from app.models.system_parameter import SystemParameter
from app.models.target_stock import TargetStock
from app.models.todo import Todo
from sqlalchemy import select, func, text

session = None

async def init():
    global session
    session = async_session()
    await session.__aenter__()

asyncio.get_event_loop().run_until_complete(init())

print("=" * 50)
print("ALT-Fast Shell  (.venv/bin/ipython -i shell.py)")
print("=" * 50)
print("사용 가능: session, select, func, text")
print("모델: Asset, News, OrderHistory, DecisionHistory, ...")
print()
print("예시:")
print("  result = await session.execute(select(News).limit(5))")
print("  rows = result.scalars().all()")
print("=" * 50)
