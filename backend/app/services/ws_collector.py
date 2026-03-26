from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.minute_candle import MinuteCandle
from app.models.target_stock import TargetStock
from app.shared.kis import KisClient

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
TRADE_TICK_KEY_PATTERN = "ws:trade:{stock_code}"
QUOTE_TICK_KEY_PATTERN = "ws:quote:{stock_code}"
TICK_RETENTION_HOURS = 1


def _trade_tick_key(stock_code: str) -> str:
    return TRADE_TICK_KEY_PATTERN.format(stock_code=stock_code)


def quote_tick_key(stock_code: str) -> str:
    return QUOTE_TICK_KEY_PATTERN.format(stock_code=stock_code)


def _resolve_now(now: datetime | None) -> datetime:
    base = now or datetime.now(KST)
    if base.tzinfo is None:
        return base.replace(tzinfo=KST)
    return base.astimezone(KST)


def _serialize_payload(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode_member(raw_member: object) -> str:
    if isinstance(raw_member, bytes):
        return raw_member.decode("utf-8")
    return str(raw_member)


def _parse_time_or_raise(raw_time: str, field_name: str) -> None:
    try:
        datetime.strptime(raw_time, "%H:%M:%S")
    except ValueError as exc:
        raise ValueError(f"메시지 형식 파싱 실패: {field_name}") from exc


def _require_text(raw_value: object, field_name: str) -> str:
    text = str(raw_value).strip() if raw_value is not None else ""
    if not text:
        raise ValueError(f"웹소켓 필수 필드 누락: {field_name}")
    return text


def _require_int(raw_value: object, field_name: str) -> int:
    if raw_value in (None, ""):
        raise ValueError(f"웹소켓 필수 필드 누락: {field_name}")
    try:
        return int(str(raw_value).strip().replace(",", ""))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"메시지 숫자 파싱 실패: {field_name}") from exc


async def get_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.REDIS_URL, decode_responses=False)


async def save_trade_tick(stock_code: str, tick: dict, now: datetime | None = None) -> None:
    collected_at = _resolve_now(now)

    trade_id = _require_text(tick.get("trade_id"), "trade_id")
    trade_time = _require_text(tick.get("trade_time"), "trade_time")
    _parse_time_or_raise(trade_time, "trade_time")
    price = _require_int(tick.get("price"), "price")
    volume = _require_int(tick.get("volume"), "volume")

    payload = {
        "trade_id": trade_id,
        "trade_time": trade_time,
        "price": price,
        "volume": volume,
    }
    # buy_qty/sell_qty는 있으면 저장 (누적 매수/매도 수량)
    if tick.get("buy_qty") is not None:
        payload["buy_qty"] = int(tick["buy_qty"])
    if tick.get("sell_qty") is not None:
        payload["sell_qty"] = int(tick["sell_qty"])
    redis_client = await get_redis()
    try:
        await redis_client.zadd(
            _trade_tick_key(stock_code),
            {_serialize_payload(payload).encode(): collected_at.timestamp()},
            nx=True,
        )
        await trim_ticks(stock_code, now=collected_at, redis_client=redis_client)
    finally:
        await redis_client.aclose()


async def save_quote_tick(stock_code: str, tick: dict, now: datetime | None = None) -> None:
    collected_at = _resolve_now(now)

    quote_time = _require_text(tick.get("quote_time"), "quote_time")
    _parse_time_or_raise(quote_time, "quote_time")

    payload: dict = {"quote_time": quote_time}

    # 5호가 데이터
    for i in range(1, 6):
        payload[f"ask_price{i}"] = _require_int(tick.get(f"ask_price{i}"), f"ask_price{i}")
        payload[f"bid_price{i}"] = _require_int(tick.get(f"bid_price{i}"), f"bid_price{i}")
        payload[f"ask_volume{i}"] = _require_int(tick.get(f"ask_volume{i}"), f"ask_volume{i}")
        payload[f"bid_volume{i}"] = _require_int(tick.get(f"bid_volume{i}"), f"bid_volume{i}")

    if tick.get("total_ask_volume") is not None:
        payload["total_ask_volume"] = int(tick["total_ask_volume"])
    if tick.get("total_bid_volume") is not None:
        payload["total_bid_volume"] = int(tick["total_bid_volume"])
    redis_client = await get_redis()
    try:
        await redis_client.zadd(
            quote_tick_key(stock_code),
            {_serialize_payload(payload).encode(): collected_at.timestamp()},
            nx=True,
        )
        await trim_ticks(stock_code, now=collected_at, redis_client=redis_client)
    finally:
        await redis_client.aclose()


async def trim_ticks(
    stock_code: str,
    now: datetime | None = None,
    redis_client: aioredis.Redis | None = None,
) -> None:
    current_time = _resolve_now(now)
    cutoff = (current_time - timedelta(hours=TICK_RETENTION_HOURS)).timestamp()

    close_after = False
    if redis_client is None:
        redis_client = await get_redis()
        close_after = True

    try:
        await redis_client.zremrangebyscore(_trade_tick_key(stock_code), "-inf", cutoff)
        await redis_client.zremrangebyscore(quote_tick_key(stock_code), "-inf", cutoff)
    finally:
        if close_after:
            await redis_client.aclose()


async def build_candles(session: AsyncSession, stock_code: str, minutes: int = 30) -> list[MinuteCandle]:
    """Redis에 저장된 틱 데이터로 분봉을 생성하여 DB에 저장한다."""
    collected_at = _resolve_now(None)
    min_collected_at = collected_at - timedelta(minutes=minutes)

    redis_client = await get_redis()
    try:
        raw_ticks = await redis_client.zrangebyscore(
            _trade_tick_key(stock_code),
            min_collected_at.timestamp(),
            "+inf",
            withscores=True,
        )
    finally:
        await redis_client.aclose()

    # Group ticks by minute
    buckets: dict[datetime, list[tuple[int, int]]] = {}
    for raw_member, score in raw_ticks:
        try:
            payload = json.loads(_decode_member(raw_member))
        except json.JSONDecodeError:
            continue

        price = int(payload["price"])
        volume = int(payload["volume"])
        tick_time = datetime.fromtimestamp(float(score), tz=KST)
        minute_at = tick_time.replace(second=0, microsecond=0, tzinfo=None)
        buckets.setdefault(minute_at, []).append((price, volume))

    # Build candles and upsert to DB
    candles: list[MinuteCandle] = []
    for minute_at in sorted(buckets):
        ticks = buckets[minute_at]
        prices = [t[0] for t in ticks]
        volumes = [t[1] for t in ticks]

        result = await session.execute(
            select(MinuteCandle).where(
                MinuteCandle.stock_code == stock_code,
                MinuteCandle.minute_at == minute_at,
            )
        )
        candle = result.scalar_one_or_none()

        defaults = {
            "open": prices[0],
            "high": max(prices),
            "low": min(prices),
            "close": prices[-1],
            "volume": sum(volumes),
        }

        if candle is None:
            candle = MinuteCandle(stock_code=stock_code, minute_at=minute_at, **defaults)
            session.add(candle)
        else:
            for key, value in defaults.items():
                setattr(candle, key, value)

        candles.append(candle)

    if candles:
        await session.commit()

    return candles


async def run_ws_subscriber(stock_codes: list[str] | None = None) -> None:
    """KIS WebSocket 구독을 시작하고, 체결/호가 데이터를 Redis에 저장한다."""
    from app.database import async_session
    from app.shared.kis_ws import KisWebSocketClient

    if stock_codes is None:
        async with async_session() as session:
            result = await session.execute(
                select(TargetStock.stock_code).where(TargetStock.is_active.is_(True))
            )
            stock_codes = list(result.scalars().all())

    if not stock_codes:
        logger.warning("구독할 종목이 없습니다")
        return

    async def on_trade(stock_code: str, tick: dict) -> None:
        await save_trade_tick(stock_code, tick)

    async def on_orderbook(stock_code: str, tick: dict) -> None:
        await save_quote_tick(stock_code, tick)

    client = KisWebSocketClient()
    await client.connect(stock_codes, on_trade, on_orderbook)
