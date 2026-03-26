from datetime import datetime

from sqlalchemy import BigInteger, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OrderbookSnapshot(Base):
    __tablename__ = "orderbook_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(6))
    snapshot_at: Mapped[datetime] = mapped_column()

    # 매도호가 1~5 (가격 + 잔량)
    ask_price1: Mapped[int] = mapped_column()
    ask_price2: Mapped[int] = mapped_column()
    ask_price3: Mapped[int] = mapped_column()
    ask_price4: Mapped[int] = mapped_column()
    ask_price5: Mapped[int] = mapped_column()
    ask_volume1: Mapped[int] = mapped_column(BigInteger)
    ask_volume2: Mapped[int] = mapped_column(BigInteger)
    ask_volume3: Mapped[int] = mapped_column(BigInteger)
    ask_volume4: Mapped[int] = mapped_column(BigInteger)
    ask_volume5: Mapped[int] = mapped_column(BigInteger)

    # 매수호가 1~5 (가격 + 잔량)
    bid_price1: Mapped[int] = mapped_column()
    bid_price2: Mapped[int] = mapped_column()
    bid_price3: Mapped[int] = mapped_column()
    bid_price4: Mapped[int] = mapped_column()
    bid_price5: Mapped[int] = mapped_column()
    bid_volume1: Mapped[int] = mapped_column(BigInteger)
    bid_volume2: Mapped[int] = mapped_column(BigInteger)
    bid_volume3: Mapped[int] = mapped_column(BigInteger)
    bid_volume4: Mapped[int] = mapped_column(BigInteger)
    bid_volume5: Mapped[int] = mapped_column(BigInteger)

    # 총잔량
    total_ask_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_bid_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "stock_code", "snapshot_at",
            name="uq_orderbook_snapshots_stock_code_snapshot_at",
        ),
        Index("ix_orderbook_snapshots_stock_code", "stock_code"),
        Index("ix_orderbook_snapshots_snapshot_at", "snapshot_at"),
        Index(
            "ix_orderbook_snapshots_stock_code_snapshot_at",
            "stock_code", "snapshot_at",
        ),
    )
