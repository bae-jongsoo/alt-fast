from datetime import date, datetime

from sqlalchemy import Date, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(32))
    stock_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    external_id: Mapped[str] = mapped_column(String(128), unique=True)
    published_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # PER / PBR / EPS / BPS
    per: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    pbr: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    eps: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    bps: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    stac_month: Mapped[str] = mapped_column(String(64), default="")

    # 시가총액 / 자본금 등
    lstn_stcn: Mapped[str] = mapped_column(String(128), default="")
    hts_avls: Mapped[int | None] = mapped_column(nullable=True)
    cpfn: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    stck_fcam: Mapped[int | None] = mapped_column(nullable=True)

    # 52주 고저
    w52_hgpr: Mapped[int | None] = mapped_column(nullable=True)
    w52_hgpr_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    w52_hgpr_vrss_prpr_ctrt: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    w52_lwpr: Mapped[int | None] = mapped_column(nullable=True)
    w52_lwpr_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    w52_lwpr_vrss_prpr_ctrt: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)

    # 250일 고저
    d250_hgpr: Mapped[int | None] = mapped_column(nullable=True)
    d250_hgpr_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    d250_hgpr_vrss_prpr_rate: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    d250_lwpr: Mapped[int | None] = mapped_column(nullable=True)
    d250_lwpr_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    d250_lwpr_vrss_prpr_rate: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)

    # 연간 고저
    stck_dryy_hgpr: Mapped[int | None] = mapped_column(nullable=True)
    dryy_hgpr_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    dryy_hgpr_vrss_prpr_rate: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    stck_dryy_lwpr: Mapped[int | None] = mapped_column(nullable=True)
    dryy_lwpr_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    dryy_lwpr_vrss_prpr_rate: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)

    # 외국인 / 프로그램
    hts_frgn_ehrt: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    frgn_hldn_qty: Mapped[int | None] = mapped_column(nullable=True)
    frgn_ntby_qty: Mapped[int | None] = mapped_column(nullable=True)
    pgtr_ntby_qty: Mapped[int | None] = mapped_column(nullable=True)

    # 거래 / 대출 / 증거금
    vol_tnrt: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    whol_loan_rmnd_rate: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    marg_rate: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)

    # 상태 코드
    crdt_able_yn: Mapped[str] = mapped_column(String(2), default="")
    ssts_yn: Mapped[str] = mapped_column(String(2), default="")
    iscd_stat_cls_code: Mapped[str] = mapped_column(String(16), default="")
    mrkt_warn_cls_code: Mapped[str] = mapped_column(String(16), default="")
    invt_caful_yn: Mapped[str] = mapped_column(String(2), default="")
    short_over_yn: Mapped[str] = mapped_column(String(2), default="")
    sltr_yn: Mapped[str] = mapped_column(String(2), default="")
    mang_issu_cls_code: Mapped[str] = mapped_column(String(16), default="")
    temp_stop_yn: Mapped[str] = mapped_column(String(2), default="")
    oprc_rang_cont_yn: Mapped[str] = mapped_column(String(2), default="")
    clpr_rang_cont_yn: Mapped[str] = mapped_column(String(2), default="")
    grmn_rate_cls_code: Mapped[str] = mapped_column(String(16), default="")
    new_hgpr_lwpr_cls_code: Mapped[str] = mapped_column(String(16), default="")
    rprs_mrkt_kor_name: Mapped[str] = mapped_column(String(128), default="")
    bstp_kor_isnm: Mapped[str] = mapped_column(String(128), default="")
    vi_cls_code: Mapped[str] = mapped_column(String(16), default="")
    ovtm_vi_cls_code: Mapped[str] = mapped_column(String(16), default="")
    last_ssts_cntg_qty: Mapped[int | None] = mapped_column(nullable=True)
    apprch_rate: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)

    __table_args__ = (
        Index("ix_market_snapshots_stock_code", "stock_code"),
        Index("ix_market_snapshots_created_at", "created_at"),
        Index("ix_market_snapshots_published_at", "published_at"),
        Index("ix_market_snapshots_stock_code_published_at", "stock_code", "published_at"),
        Index("ix_market_snapshots_stock_code_created_at", "stock_code", "created_at"),
    )
