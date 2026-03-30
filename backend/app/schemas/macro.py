"""매크로 스냅샷 응답 스키마."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class MacroSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
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

    # 기타
    raw_data: dict[str, Any] | None = None
    created_at: datetime
