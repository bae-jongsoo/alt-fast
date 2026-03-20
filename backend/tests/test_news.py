import hashlib
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dart_disclosure import DartDisclosure
from app.models.news import News


async def _seed(db: AsyncSession):
    now = datetime.utcnow()
    db.add(News(
        stock_code="005930", stock_name="삼성전자",
        external_id=hashlib.sha256(b"n1").hexdigest(),
        title="삼성전자 실적 발표", summary="호실적",
        link="https://example.com/1", useful=True,
        published_at=now - timedelta(hours=1),
    ))
    db.add(News(
        stock_code="005930", stock_name="삼성전자",
        external_id=hashlib.sha256(b"n2").hexdigest(),
        title="삼성전자 하락", summary="외국인 매도",
        link="https://example.com/2", useful=False,
        published_at=now - timedelta(hours=2),
    ))
    db.add(News(
        stock_code="000660", stock_name="SK하이닉스",
        external_id=hashlib.sha256(b"n3").hexdigest(),
        title="HBM 수주", summary=None,
        link="https://example.com/3", useful=None,
        published_at=now - timedelta(hours=3),
    ))
    db.add(DartDisclosure(
        stock_code="005930", stock_name="삼성전자",
        external_id=hashlib.sha256(b"d1").hexdigest(),
        corp_code="00126380", rcept_no="20240320000001",
        title="사업보고서", link="https://dart.fss.or.kr/1",
        published_at=now - timedelta(hours=1),
    ))
    db.add(DartDisclosure(
        stock_code="000660", stock_name="SK하이닉스",
        external_id=hashlib.sha256(b"d2").hexdigest(),
        corp_code="00164779", rcept_no="20240320000002",
        title="분기보고서", link="https://dart.fss.or.kr/2",
        published_at=now - timedelta(hours=2),
    ))
    await db.commit()


class TestNewsAPI:
    @pytest.fixture(autouse=True)
    async def seed(self, db):
        await _seed(db)

    async def test_list_all(self, client):
        resp = await client.get("/api/news")
        assert resp.status_code == 200
        assert resp.json()["total"] == 3

    async def test_filter_stock_code(self, client):
        resp = await client.get("/api/news?stock_code=005930")
        assert resp.json()["total"] == 2

    async def test_filter_useful_true(self, client):
        resp = await client.get("/api/news?useful=true")
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["useful"] is True

    async def test_filter_useful_null(self, client):
        resp = await client.get("/api/news?useful=null")
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["useful"] is None


class TestDartAPI:
    @pytest.fixture(autouse=True)
    async def seed(self, db):
        await _seed(db)

    async def test_list_all(self, client):
        resp = await client.get("/api/dart")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    async def test_filter_stock_code(self, client):
        resp = await client.get("/api/dart?stock_code=000660")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "분기보고서"
