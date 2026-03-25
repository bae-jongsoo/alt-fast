"""KIS WebSocket 직접 구현 — 체결(H0STCNT0) + 호가(H0STASP0) 수신."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import websockets

from app.config import settings

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
KIS_WS_URL = "ws://ops.koreainvestment.com:21000"
KIS_APPROVAL_URL = "https://openapi.koreainvestment.com:9443/oauth2/Approval"
APPROVAL_KEY_CACHE_PATH = Path.home() / ".kis_ws_approval_key"
APPROVAL_KEY_TTL_HOURS = 12

# TR IDs
TR_TRADE = "H0STCNT0"  # 실시간 체결
TR_ORDERBOOK = "H0STASP0"  # 실시간 호가

OnTradeCallback = Callable[[str, dict], Coroutine[Any, Any, None]]
OnOrderbookCallback = Callable[[str, dict], Coroutine[Any, Any, None]]


class KisWebSocketClient:
    """KIS WebSocket 직접 구현 — pykis 의존 없이 체결 + 호가 수신."""

    def __init__(self, app_key: str | None = None, app_secret: str | None = None):
        self.app_key = app_key or settings.KIS_APP_KEY
        self.app_secret = app_secret or settings.KIS_APP_SECRET
        self._approval_key: str | None = None

    async def get_approval_key(self) -> str:
        """approval_key 발급 (캐시 우선, 만료 시 재발급)."""
        # 캐시 파일에서 읽기
        cached = self._read_cached_key()
        if cached:
            self._approval_key = cached
            return cached

        # 재발급
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                KIS_APPROVAL_URL,
                json={
                    "grant_type": "client_credentials",
                    "appkey": self.app_key,
                    "secretkey": self.app_secret,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        key = data.get("approval_key")
        if not key:
            raise RuntimeError(f"approval_key 발급 실패: {data}")

        self._approval_key = key
        self._save_cached_key(key)
        logger.info("KIS WebSocket approval_key 발급 완료")
        return key

    async def connect(
        self,
        stock_codes: list[str],
        on_trade: OnTradeCallback,
        on_orderbook: OnOrderbookCallback,
    ) -> None:
        """WebSocket 연결 + 구독 + 수신 루프. 종료 시까지 블로킹."""
        approval_key = await self.get_approval_key()

        async for ws in websockets.connect(KIS_WS_URL, ping_interval=30):
            try:
                # 구독 요청
                for code in stock_codes:
                    await self._subscribe(ws, approval_key, TR_TRADE, code)
                    await self._subscribe(ws, approval_key, TR_ORDERBOOK, code)

                logger.info("KIS WebSocket 구독 시작: %d종목", len(stock_codes))

                # 수신 루프
                async for raw in ws:
                    try:
                        await self._handle_message(
                            str(raw), on_trade, on_orderbook
                        )
                    except Exception:
                        logger.exception("WS 메시지 처리 실패")

            except websockets.ConnectionClosed:
                logger.warning("KIS WebSocket 연결 종료, 재연결 시도...")
                continue
            except Exception:
                logger.exception("KIS WebSocket 오류")
                break

    @staticmethod
    async def _subscribe(
        ws: websockets.ClientConnection,
        approval_key: str,
        tr_id: str,
        tr_key: str,
    ) -> None:
        """구독 요청 전송."""
        msg = json.dumps({
            "header": {
                "approval_key": approval_key,
                "custtype": "P",
                "tr_type": "1",
                "content-type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": tr_id,
                    "tr_key": tr_key,
                },
            },
        })
        await ws.send(msg)

    async def _handle_message(
        self,
        raw: str,
        on_trade: OnTradeCallback,
        on_orderbook: OnOrderbookCallback,
    ) -> None:
        """수신 메시지 파싱 + 콜백 호출."""
        if not raw:
            return

        # JSON 시스템 메시지 (구독 응답, PINGPONG 등)
        if raw[0] not in ("0", "1"):
            try:
                msg = json.loads(raw)
                tr_id = msg.get("header", {}).get("tr_id", "")
                rt_cd = msg.get("body", {}).get("rt_cd", "")
                msg1 = msg.get("body", {}).get("msg1", "")
                if rt_cd == "1":
                    logger.warning("KIS WS 구독 실패: %s %s", tr_id, msg1)
                elif msg1:
                    logger.debug("KIS WS: %s %s", tr_id, msg1)
            except json.JSONDecodeError:
                logger.debug("KIS WS 비-JSON 메시지: %s", raw[:100])
            return

        # 데이터 메시지: 0|TR_ID|COUNT|data
        parts = raw.split("|", 3)
        if len(parts) < 4:
            return

        tr_id = parts[1]
        data_str = parts[3]
        fields = data_str.split("^")

        if tr_id == TR_TRADE:
            stock_code, tick = self._parse_trade(fields)
            if stock_code:
                await on_trade(stock_code, tick)
        elif tr_id == TR_ORDERBOOK:
            stock_code, tick = self._parse_orderbook(fields)
            if stock_code:
                await on_orderbook(stock_code, tick)

    @staticmethod
    def _parse_trade(fields: list[str]) -> tuple[str, dict]:
        """체결 데이터 파싱.

        주요 인덱스 (국내주식실시간체결가 H0STCNT0):
          0: MKSC_SHRN_ISCD 종목코드
          1: STCK_CNTG_HOUR 체결시간 (HHMMSS)
          2: STCK_PRPR 현재가
         12: CNTG_VOL 체결 거래량 (건별)
         13: ACML_VOL 누적 거래량
         19: SELN_CNTG_SMTN 총 매도 수량
         20: SHNU_CNTG_SMTN 총 매수 수량
        """
        if len(fields) < 21:
            return "", {}

        stock_code = fields[0]
        trade_time = fields[1]  # HHMMSS
        now = datetime.now(KST)
        time_str = f"{trade_time[:2]}:{trade_time[2:4]}:{trade_time[4:6]}"

        return stock_code, {
            "trade_id": f"{stock_code}_{now.date().isoformat()}T{time_str}+09:00",
            "trade_time": time_str,
            "price": int(fields[2]),
            "volume": int(fields[12]),      # 체결 거래량 (건별)
            "buy_qty": int(fields[20]),      # 총 매수 수량 (누적)
            "sell_qty": int(fields[19]),      # 총 매도 수량 (누적)
        }

    @staticmethod
    def _parse_orderbook(fields: list[str]) -> tuple[str, dict]:
        """호가 데이터 파싱.

        주요 인덱스 (국내주식실시간호가 H0STASP0):
          0: MKSC_SHRN_ISCD 종목코드
          1: BSOP_HOUR 영업시간 (HHMMSS)
          3: ASKP1 매도호가1 ... 12: ASKP10
         13: BIDP1 매수호가1 ... 22: BIDP10
         23: ASKP_RSQN1 매도잔량1 ... 32: ASKP_RSQN10
         33: BIDP_RSQN1 매수잔량1 ... 42: BIDP_RSQN10
         43: TOTAL_ASKP_RSQN 총 매도잔량
         44: TOTAL_BIDP_RSQN 총 매수잔량
        """
        if len(fields) < 45:
            return "", {}

        stock_code = fields[0]
        quote_time = fields[1]  # HHMMSS
        time_str = f"{quote_time[:2]}:{quote_time[2:4]}:{quote_time[4:6]}"

        return stock_code, {
            "quote_time": time_str,
            "ask_price": int(fields[3]),     # 매도 1호가
            "bid_price": int(fields[13]),    # 매수 1호가
            "ask_volume": int(fields[23]),   # 매도 1호가 잔량
            "bid_volume": int(fields[33]),   # 매수 1호가 잔량
            "total_ask_volume": int(fields[43]),  # 총 매도 잔량
            "total_bid_volume": int(fields[44]),  # 총 매수 잔량
        }

    # -- approval_key 캐시 --

    @staticmethod
    def _read_cached_key() -> str | None:
        """캐시 파일에서 approval_key 읽기. 만료 시 None."""
        try:
            if not APPROVAL_KEY_CACHE_PATH.exists():
                return None
            data = json.loads(APPROVAL_KEY_CACHE_PATH.read_text())
            expires_at = datetime.fromisoformat(data["expires_at"])
            if datetime.now(KST) >= expires_at:
                return None
            return data["approval_key"]
        except Exception:
            return None

    @staticmethod
    def _save_cached_key(key: str) -> None:
        """approval_key를 캐시 파일에 저장."""
        try:
            data = {
                "approval_key": key,
                "expires_at": (
                    datetime.now(KST) + timedelta(hours=APPROVAL_KEY_TTL_HOURS)
                ).isoformat(),
            }
            APPROVAL_KEY_CACHE_PATH.write_text(json.dumps(data))
        except Exception:
            logger.warning("approval_key 캐시 저장 실패")
