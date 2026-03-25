from __future__ import annotations

import logging
import signal
from collections.abc import Callable
from threading import Event

import httpx
from pykis import PyKis
from pykis.api.websocket.order_book import KisRealtimeOrderbook
from pykis.api.websocket.price import KisRealtimePrice
from pykis.event.subscription import KisSubscriptionEventArgs

from app.config import settings

logger = logging.getLogger(__name__)

KIS_BASE_URL = "https://openapi.koreainvestment.com:9443"
KIS_INQUIRE_PRICE_URL = (
    f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price"
)
KIS_TR_ID_INQUIRE_PRICE = "FHKST01010100"


class KisClient:
    """PyKis를 내포하여 토큰 관리 / REST API / WebSocket 구독을 통합 제공."""

    def __init__(self, *, use_websocket: bool = False):
        self._kis = PyKis(
            id=settings.KIS_HTS_ID,
            appkey=settings.KIS_APP_KEY,
            secretkey=settings.KIS_APP_SECRET,
            account=settings.KIS_ACCT_STOCK,
            keep_token=True,
            use_websocket=use_websocket,
        )

    @property
    def access_token(self) -> str:
        return self._kis.token.token

    # -- REST API (async) ------------------------------------------

    async def fetch_inquire_price(self, stock_code: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(
                    KIS_INQUIRE_PRICE_URL,
                    headers={
                        "authorization": f"Bearer {self.access_token}",
                        "appkey": settings.KIS_APP_KEY,
                        "appsecret": settings.KIS_APP_SECRET,
                        "tr_id": KIS_TR_ID_INQUIRE_PRICE,
                        "custtype": "P",
                    },
                    params={
                        "fid_cond_mrkt_div_code": "J",
                        "fid_input_iscd": stock_code,
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"KIS 현재정보 조회 실패: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("KIS 응답 JSON 파싱 실패") from exc

        if str(payload.get("rt_cd")) != "0":
            error_message = (
                payload.get("msg1") or payload.get("msg_cd") or "알 수 없는 오류"
            )
            raise RuntimeError(f"KIS API 오류/실패: {error_message}")

        output = payload.get("output")
        if not isinstance(output, dict):
            raise RuntimeError("KIS API 비정상 응답: output 필드가 없습니다")

        return output

    # -- WebSocket (동기 blocking) ---------------------------------

    def subscribe_realtime(
        self,
        stock_codes: list[str],
        on_trade: Callable[[str, dict], None],
        on_orderbook: Callable[[str, dict], None] | None = None,
    ) -> None:
        """KIS WebSocket 구독 시작. SIGTERM/SIGINT 까지 블로킹."""
        stop = Event()

        def _on_price(
            _client: object,
            event: KisSubscriptionEventArgs[KisRealtimePrice],
        ) -> None:
            try:
                stock_code, tick = self._map_trade_event(event.response)
                on_trade(stock_code, tick)
            except Exception:
                logger.exception("체결 이벤트 처리 실패")

        def _on_orderbook(
            _client: object,
            event: KisSubscriptionEventArgs[KisRealtimeOrderbook],
        ) -> None:
            try:
                stock_code, tick = self._map_orderbook_event(event.response)
                on_orderbook(stock_code, tick)
            except Exception:
                logger.exception("호가 이벤트 처리 실패")

        tickets = []
        for code in stock_codes:
            stock = self._kis.stock(symbol=code, market="KRX")
            tickets.append(stock.on(event="price", callback=_on_price))
            if on_orderbook is not None:
                tickets.append(stock.on(event="orderbook", callback=_on_orderbook))

        logger.info("ws 구독 시작 종목수=%d", len(stock_codes))

        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())

        try:
            while not stop.is_set():
                stop.wait(1.0)
        finally:
            self._kis.websocket.disconnect()
            logger.info("ws 구독 종료")

    @staticmethod
    def _map_trade_event(response: KisRealtimePrice) -> tuple[str, dict]:
        stock_code = str(response.symbol)
        time_kst = response.time_kst
        return stock_code, {
            "trade_id": f"{stock_code}_{time_kst.isoformat()}",
            "trade_time": time_kst.strftime("%H:%M:%S"),
            "price": int(response.price),
            "volume": int(response.__data__[12]),  # CNTG_VOL 체결 거래량 (건별)
            "buy_qty": int(response.buy_quantity),   # SHNU_CNTG_SMTN 총 매수 수량 (누적)
            "sell_qty": int(response.sell_quantity),  # SELN_CNTG_SMTN 총 매도 수량 (누적)
        }

    @staticmethod
    def _map_orderbook_event(response: KisRealtimeOrderbook) -> tuple[str, dict]:
        stock_code = str(response.symbol)
        time_kst = response.time_kst
        return stock_code, {
            "quote_time": time_kst.strftime("%H:%M:%S"),
            "ask_price": int(response.ask_price),
            "bid_price": int(response.bid_price),
            "ask_volume": int(response.ask_volume),
            "bid_volume": int(response.bid_volume),
        }
