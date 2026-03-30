"""Yahoo Finance 기반 매크로 데이터 수집 모듈."""

import asyncio
import logging
from datetime import date
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# yfinance 티커 매핑: (티커, close 필드명, change_pct 필드명)
TICKER_MAP: list[tuple[str, str, str | None]] = [
    # 미국 지수
    ("^GSPC", "sp500_close", "sp500_change_pct"),
    ("^IXIC", "nasdaq_close", "nasdaq_change_pct"),
    ("^DJI", "dow_close", "dow_change_pct"),
    ("^RUT", "russell2000_close", "russell2000_change_pct"),
    # 변동성
    ("^VIX", "vix", "vix_change_pct"),
    # 미국 금리 (close만, change_pct 없음)
    ("^IRX", "us_13w_tbill", None),
    ("^FVX", "us_5y_treasury", None),
    ("^TNX", "us_10y_treasury", None),
    ("^TYX", "us_30y_treasury", None),
    # 환율
    ("USDKRW=X", "usd_krw", "usd_krw_change_pct"),
    ("USDCNY=X", "usd_cny", "usd_cny_change_pct"),
    ("USDJPY=X", "usd_jpy", "usd_jpy_change_pct"),
    ("DX-Y.NYB", "dxy", "dxy_change_pct"),
    # 원자재
    ("GC=F", "gold", "gold_change_pct"),
    ("CL=F", "wti", "wti_change_pct"),
    ("HG=F", "copper", "copper_change_pct"),
    # 아시아 지수
    ("^N225", "nikkei_close", "nikkei_change_pct"),
    ("^HSI", "hang_seng_close", "hang_seng_change_pct"),
    ("000001.SS", "shanghai_close", "shanghai_change_pct"),
    # 반도체/한국
    ("^SOX", "sox_close", "sox_change_pct"),
    ("EWY", "ewy_close", "ewy_change_pct"),
    ("138230.KS", "kr_bond_10y_close", "kr_bond_10y_change_pct"),
]


class MacroData(BaseModel):
    """매크로 데이터 수집 결과."""

    snapshot_date: date

    # 미국 지수
    sp500_close: float | None = None
    sp500_change_pct: float | None = None
    nasdaq_close: float | None = None
    nasdaq_change_pct: float | None = None
    dow_close: float | None = None
    dow_change_pct: float | None = None
    russell2000_close: float | None = None
    russell2000_change_pct: float | None = None

    # 변동성
    vix: float | None = None
    vix_change_pct: float | None = None

    # 미국 금리
    us_13w_tbill: float | None = None
    us_5y_treasury: float | None = None
    us_10y_treasury: float | None = None
    us_30y_treasury: float | None = None

    # 환율
    usd_krw: float | None = None
    usd_krw_change_pct: float | None = None
    usd_cny: float | None = None
    usd_cny_change_pct: float | None = None
    usd_jpy: float | None = None
    usd_jpy_change_pct: float | None = None
    dxy: float | None = None
    dxy_change_pct: float | None = None

    # 원자재
    gold: float | None = None
    gold_change_pct: float | None = None
    wti: float | None = None
    wti_change_pct: float | None = None
    copper: float | None = None
    copper_change_pct: float | None = None

    # 아시아 지수
    nikkei_close: float | None = None
    nikkei_change_pct: float | None = None
    hang_seng_close: float | None = None
    hang_seng_change_pct: float | None = None
    shanghai_close: float | None = None
    shanghai_change_pct: float | None = None

    # 반도체/한국
    sox_close: float | None = None
    sox_change_pct: float | None = None
    ewy_close: float | None = None
    ewy_change_pct: float | None = None
    kr_bond_10y_close: float | None = None
    kr_bond_10y_change_pct: float | None = None

    # 한국 기준금리
    kr_base_rate: float | None = None

    # 원본 데이터
    raw_data: dict[str, Any] | None = None


def _download_yfinance(
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    """yfinance로 20개 티커 배치 다운로드 (동기 함수).

    start/end가 주어지면 해당 기간 데이터를 다운로드하고,
    없으면 기존처럼 period="2d"를 사용한다.
    """
    import yfinance as yf

    tickers = [t[0] for t in TICKER_MAP]
    ticker_str = " ".join(tickers)

    logger.info("yfinance 배치 다운로드 시작: %d개 티커", len(tickers))
    if start is not None and end is not None:
        df = yf.download(
            tickers=ticker_str,
            start=start.isoformat(),
            end=end.isoformat(),
            progress=False,
            auto_adjust=True,
        )
    else:
        df = yf.download(tickers=ticker_str, period="2d", progress=False, auto_adjust=True)
    logger.info("yfinance 배치 다운로드 완료: shape=%s", df.shape if df is not None else "None")

    result: dict[str, Any] = {}

    if df is None or df.empty:
        return result

    for ticker, close_field, change_field in TICKER_MAP:
        try:
            # yf.download with multiple tickers returns MultiIndex columns: (metric, ticker)
            close_col = ("Close", ticker)
            if close_col not in df.columns:
                logger.warning("티커 %s: Close 컬럼 없음", ticker)
                continue

            series = df[close_col].dropna()
            if len(series) == 0:
                logger.warning("티커 %s: 데이터 없음", ticker)
                continue

            # 최신 종가
            latest_close = float(series.iloc[-1])
            result[close_field] = round(latest_close, 6)

            # 전일 대비 등락률
            if change_field and len(series) >= 2:
                prev_close = float(series.iloc[-2])
                if prev_close != 0:
                    change_pct = ((latest_close - prev_close) / prev_close) * 100
                    result[change_field] = round(change_pct, 6)

        except Exception:
            logger.exception("티커 %s 처리 실패", ticker)

    return result


async def fetch_macro_data(target_date: date | None = None) -> MacroData:
    """매크로 데이터를 yfinance에서 수집하여 MacroData로 반환.

    yfinance는 동기 라이브러리이므로 asyncio.to_thread()로 래핑.
    """
    if target_date is None:
        target_date = date.today()

    raw = await asyncio.to_thread(_download_yfinance)

    return MacroData(
        snapshot_date=target_date,
        raw_data=raw,
        **{k: v for k, v in raw.items() if k != "raw_data"},
    )


def _download_yfinance_range(start: date, end: date) -> dict[date, dict[str, Any]]:
    """yfinance로 기간별 일별 데이터를 다운로드 (동기 함수).

    Returns:
        {날짜: {필드명: 값}} 형태의 dict
    """
    import yfinance as yf
    from datetime import timedelta

    tickers = [t[0] for t in TICKER_MAP]
    ticker_str = " ".join(tickers)

    # yfinance end는 exclusive이므로 +1일
    end_exclusive = end + timedelta(days=1)

    logger.info(
        "yfinance 기간별 다운로드 시작: %d개 티커, %s ~ %s",
        len(tickers), start, end,
    )
    df = yf.download(
        tickers=ticker_str,
        start=start.isoformat(),
        end=end_exclusive.isoformat(),
        progress=False,
        auto_adjust=True,
    )
    logger.info(
        "yfinance 기간별 다운로드 완료: shape=%s",
        df.shape if df is not None else "None",
    )

    result: dict[date, dict[str, Any]] = {}

    if df is None or df.empty:
        return result

    for idx in df.index:
        row_date = idx.date() if hasattr(idx, "date") else idx
        day_data: dict[str, Any] = {}

        for ticker, close_field, change_field in TICKER_MAP:
            try:
                close_col = ("Close", ticker)
                if close_col not in df.columns:
                    continue

                val = df.loc[idx, close_col]
                if val is not None and not (isinstance(val, float) and val != val):
                    day_data[close_field] = round(float(val), 6)

                    # 전일 대비 등락률 계산: 전일 데이터가 있으면 계산
                    if change_field:
                        loc = df.index.get_loc(idx)
                        if loc > 0:
                            prev_val = df.iloc[loc - 1][close_col]
                            if (
                                prev_val is not None
                                and not (isinstance(prev_val, float) and prev_val != prev_val)
                                and float(prev_val) != 0
                            ):
                                change_pct = ((float(val) - float(prev_val)) / float(prev_val)) * 100
                                day_data[change_field] = round(change_pct, 6)

            except Exception:
                logger.exception("티커 %s 기간별 처리 실패 (%s)", ticker, row_date)

        if day_data:
            result[row_date] = day_data

    return result


async def fetch_macro_data_range(
    start_date: date,
    end_date: date,
) -> list[MacroData]:
    """기간별 매크로 데이터를 yfinance에서 수집하여 MacroData 리스트로 반환.

    Args:
        start_date: 수집 시작일
        end_date: 수집 종료일 (inclusive)

    Returns:
        일별 MacroData 리스트
    """
    raw_by_date = await asyncio.to_thread(_download_yfinance_range, start_date, end_date)

    results: list[MacroData] = []
    for d, raw in sorted(raw_by_date.items()):
        results.append(
            MacroData(
                snapshot_date=d,
                raw_data=raw,
                **{k: v for k, v in raw.items() if k != "raw_data"},
            )
        )

    return results
