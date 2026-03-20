from datetime import datetime

from sqlalchemy import Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MinuteCandle(Base):
    __tablename__ = "minute_candles"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(6))
    minute_at: Mapped[datetime] = mapped_column()
    open: Mapped[int] = mapped_column()
    high: Mapped[int] = mapped_column()
    low: Mapped[int] = mapped_column()
    close: Mapped[int] = mapped_column()
    volume: Mapped[int] = mapped_column()

    __table_args__ = (
        UniqueConstraint("stock_code", "minute_at", name="uq_minute_candles_stock_code_minute_at"),
        Index("ix_minute_candles_stock_code", "stock_code"),
        Index("ix_minute_candles_minute_at", "minute_at"),
        Index("ix_minute_candles_stock_code_minute_at", "stock_code", "minute_at"),
    )
