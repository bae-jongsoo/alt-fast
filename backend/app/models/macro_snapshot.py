from datetime import date, datetime

from sqlalchemy import Date, JSON, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MacroSnapshot(Base):
    __tablename__ = "macro_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, unique=True)

    # 미국 지수
    sp500_close: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    sp500_change_pct: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    nasdaq_close: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    nasdaq_change_pct: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    dow_close: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    dow_change_pct: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    russell2000_close: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    russell2000_change_pct: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)

    # 변동성
    vix: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    vix_change_pct: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)

    # 미국 금리
    us_13w_tbill: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    us_5y_treasury: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    us_10y_treasury: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    us_30y_treasury: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)

    # 환율
    usd_krw: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    usd_krw_change_pct: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    usd_cny: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    usd_cny_change_pct: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    usd_jpy: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    usd_jpy_change_pct: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    dxy: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    dxy_change_pct: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)

    # 원자재
    gold: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    gold_change_pct: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    wti: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    wti_change_pct: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    copper: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    copper_change_pct: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)

    # 아시아 지수
    nikkei_close: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    nikkei_change_pct: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    hang_seng_close: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    hang_seng_change_pct: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    shanghai_close: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    shanghai_change_pct: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)

    # 반도체/한국 관련
    sox_close: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    sox_change_pct: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    ewy_close: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    ewy_change_pct: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    kr_bond_10y_close: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    kr_bond_10y_change_pct: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)

    # 한국 기준금리
    kr_base_rate: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)

    # 기타
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
