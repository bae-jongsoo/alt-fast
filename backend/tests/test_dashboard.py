from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.decision_history import DecisionHistory
from app.models.minute_candle import MinuteCandle
from app.models.order_history import OrderHistory


async def _seed_data(db: AsyncSession):
    now = datetime.utcnow()

    # 현금
    db.add(Asset(stock_code=None, stock_name=None, quantity=0, unit_price=0, total_amount=10_000_000))
    # 보유종목
    db.add(Asset(stock_code="005930", stock_name="삼성전자", quantity=10, unit_price=70000, total_amount=700000))
    # 분봉 (현재가)
    db.add(MinuteCandle(
        stock_code="005930", minute_at=now - timedelta(minutes=1),
        open=71000, high=72000, low=70500, close=71500, volume=1000,
    ))

    # 판단 이력
    d_buy = DecisionHistory(stock_code="005930", stock_name="삼성전자", decision="BUY")
    d_sell = DecisionHistory(stock_code="005930", stock_name="삼성전자", decision="SELL")
    d_hold = DecisionHistory(stock_code="005930", stock_name="삼성전자", decision="HOLD")
    d_error = DecisionHistory(
        stock_code="005930", stock_name="삼성전자", decision="HOLD",
        is_error=True, error_message="LLM timeout",
    )
    db.add_all([d_buy, d_sell, d_hold, d_error])
    await db.flush()

    # 주문 이력 (FK 연결)
    db.add(OrderHistory(
        decision_history_id=d_buy.id, stock_code="005930", stock_name="삼성전자",
        order_type="BUY", order_price=70000, order_quantity=10,
        order_total_amount=700000, result_price=70000, result_quantity=10,
        result_total_amount=700000,
    ))
    db.add(OrderHistory(
        decision_history_id=d_sell.id, stock_code="005930", stock_name="삼성전자",
        order_type="SELL", order_price=71500, order_quantity=5,
        order_total_amount=357500, result_price=71500, result_quantity=5,
        result_total_amount=357500, profit_loss=7500, profit_rate=2.14,
    ))

    await db.commit()


class TestDashboardEmpty:
    async def test_empty_dashboard(self, client):
        resp = await client.get("/api/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["total_asset_value"] == 0.0
        assert data["summary"]["cash_balance"] == 0.0
        assert data["holdings"] == []
        assert data["recent_orders"] == []
        assert data["recent_errors"] == []
        assert data["trading_summary"]["total_decisions"] == 0

    async def test_system_status_all_stopped(self, client):
        resp = await client.get("/api/dashboard")
        data = resp.json()
        for s in data["system_status"]:
            assert s["status"] == "stopped"
            assert s["last_active_at"] is None


class TestDashboardWithData:
    @pytest.fixture(autouse=True)
    async def seed(self, db):
        await _seed_data(db)

    async def test_summary_card(self, client):
        resp = await client.get("/api/dashboard")
        assert resp.status_code == 200
        summary = resp.json()["summary"]

        assert summary["cash_balance"] == 10_000_000
        # 현금 10,000,000 + 삼성전자 10주 * 71500 = 10,715,000
        assert summary["total_asset_value"] == 10_715_000
        assert summary["today_realized_pnl"] == 7500
        assert summary["today_buy_count"] == 1
        assert summary["today_sell_count"] == 1
        assert summary["today_trade_count"] == 2

    async def test_holdings(self, client):
        holdings = (await client.get("/api/dashboard")).json()["holdings"]
        assert len(holdings) == 1
        h = holdings[0]
        assert h["stock_code"] == "005930"
        assert h["quantity"] == 10
        assert h["current_price"] == 71500
        assert h["eval_pnl"] == 15000
        assert h["profit_rate"] == pytest.approx(2.14, abs=0.01)

    async def test_trading_summary(self, client):
        ts = (await client.get("/api/dashboard")).json()["trading_summary"]
        assert ts["total_decisions"] == 4
        assert ts["buy_count"] == 1
        assert ts["sell_count"] == 1
        assert ts["hold_count"] == 2
        assert ts["error_count"] == 1

    async def test_recent_orders(self, client):
        orders = (await client.get("/api/dashboard")).json()["recent_orders"]
        assert len(orders) == 2
        assert orders[0]["order_type"] == "SELL"
        assert orders[1]["order_type"] == "BUY"

    async def test_recent_errors(self, client):
        errors = (await client.get("/api/dashboard")).json()["recent_errors"]
        assert len(errors) == 1
        assert errors[0]["error_message"] == "LLM timeout"

    async def test_system_status_ws_normal(self, client):
        ws = next(
            s for s in (await client.get("/api/dashboard")).json()["system_status"]
            if s["name"] == "ws"
        )
        assert ws["status"] == "normal"
