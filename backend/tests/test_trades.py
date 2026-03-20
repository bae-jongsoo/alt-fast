import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.decision_history import DecisionHistory
from app.models.order_history import OrderHistory


async def _seed(db: AsyncSession):
    d1 = DecisionHistory(stock_code="005930", stock_name="삼성전자", decision="BUY")
    d2 = DecisionHistory(stock_code="005930", stock_name="삼성전자", decision="SELL")
    d3 = DecisionHistory(stock_code="000660", stock_name="SK하이닉스", decision="HOLD")
    d4 = DecisionHistory(
        stock_code="005930", stock_name="삼성전자", decision="HOLD",
        is_error=True, error_message="timeout",
    )
    db.add_all([d1, d2, d3, d4])
    await db.flush()

    db.add(OrderHistory(
        decision_history_id=d1.id, stock_code="005930", stock_name="삼성전자",
        order_type="BUY", order_price=70000, order_quantity=10,
        order_total_amount=700000, result_price=70000, result_quantity=10,
        result_total_amount=700000,
    ))
    db.add(OrderHistory(
        decision_history_id=d2.id, stock_code="005930", stock_name="삼성전자",
        order_type="SELL", order_price=72000, order_quantity=5,
        order_total_amount=360000, result_price=72000, result_quantity=5,
        result_total_amount=360000, profit_loss=10000, profit_rate=2.86,
    ))
    await db.commit()
    return d1, d2


class TestOrdersAPI:
    @pytest.fixture(autouse=True)
    async def seed(self, db):
        await _seed(db)

    async def test_list_orders(self, client):
        resp = await client.get("/api/trades/orders")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2
        assert data["items"][0]["order_type"] == "SELL"  # 최신순

    async def test_filter_by_order_type(self, client):
        resp = await client.get("/api/trades/orders?order_type=BUY")
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["order_type"] == "BUY"

    async def test_filter_by_stock_code(self, client):
        resp = await client.get("/api/trades/orders?stock_code=000660")
        assert resp.json()["total"] == 0


class TestDecisionsAPI:
    @pytest.fixture(autouse=True)
    async def seed(self, db):
        await _seed(db)

    async def test_list_decisions(self, client):
        resp = await client.get("/api/trades/decisions")
        assert resp.status_code == 200
        assert resp.json()["total"] == 4

    async def test_filter_errors_only(self, client):
        resp = await client.get("/api/trades/decisions?errors_only=true")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["is_error"] is True

    async def test_filter_by_decision(self, client):
        resp = await client.get("/api/trades/decisions?decision=HOLD")
        assert resp.json()["total"] == 2

    async def test_decision_detail(self, client):
        # 먼저 목록에서 ID 가져오기
        list_resp = await client.get("/api/trades/decisions?decision=BUY")
        buy_id = list_resp.json()["items"][0]["id"]

        resp = await client.get(f"/api/trades/decisions/{buy_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "BUY"
        assert data["linked_order"] is not None
        assert data["linked_order"]["order_type"] == "BUY"

    async def test_decision_detail_404(self, client):
        resp = await client.get("/api/trades/decisions/99999")
        assert resp.status_code == 404
