from datetime import datetime

from sqlalchemy import ForeignKey, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OrderHistory(Base):
    __tablename__ = "order_histories"

    id: Mapped[int] = mapped_column(primary_key=True)
    decision_history_id: Mapped[int] = mapped_column(
        ForeignKey("decision_histories.id", ondelete="CASCADE")
    )
    stock_code: Mapped[str] = mapped_column(String(32))
    stock_name: Mapped[str] = mapped_column(String(50))
    order_type: Mapped[str] = mapped_column(String(4))  # BUY / SELL
    order_price: Mapped[float] = mapped_column(Numeric(20, 2))
    order_quantity: Mapped[int] = mapped_column()
    order_total_amount: Mapped[float] = mapped_column(Numeric(20, 2))
    result_price: Mapped[float] = mapped_column(Numeric(20, 2))
    result_quantity: Mapped[int] = mapped_column()
    result_total_amount: Mapped[float] = mapped_column(Numeric(20, 2))
    buy_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("order_histories.id", ondelete="SET NULL"), nullable=True
    )
    profit_loss: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    profit_rate: Mapped[float | None] = mapped_column(nullable=True)
    profit_loss_net: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    profit_rate_net: Mapped[float | None] = mapped_column(nullable=True)
    order_placed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    result_executed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("ix_order_histories_stock_code", "stock_code"),
        Index("ix_order_histories_order_placed_at", "order_placed_at"),
        Index("ix_order_histories_result_executed_at", "result_executed_at"),
        Index("ix_order_histories_created_at", "created_at"),
        Index("ix_order_histories_stock_code_created_at", "stock_code", "created_at"),
    )
