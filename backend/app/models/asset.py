from datetime import datetime

from sqlalchemy import ForeignKey, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_id: Mapped[int] = mapped_column(
        ForeignKey("strategies.id", ondelete="CASCADE")
    )
    stock_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stock_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    quantity: Mapped[int] = mapped_column()
    unit_price: Mapped[float] = mapped_column(Numeric(20, 2))
    total_amount: Mapped[float] = mapped_column(Numeric(20, 2))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("strategy_id", "stock_code", name="uq_assets_strategy_stock"),
        Index("ix_assets_strategy_id", "strategy_id"),
        Index("ix_assets_stock_code", "stock_code"),
        Index("ix_assets_stock_code_updated_at", "stock_code", "updated_at"),
    )
