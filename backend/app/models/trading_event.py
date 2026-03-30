from datetime import datetime

from sqlalchemy import ForeignKey, Index, JSON, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TradingEvent(Base):
    __tablename__ = "trading_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(32))  # dart_disclosure, news_cluster, volume_spike
    stock_code: Mapped[str] = mapped_column(String(32))
    stock_name: Mapped[str] = mapped_column(String(50))
    event_data: Mapped[dict | None] = mapped_column(JSON, default=dict, nullable=True)
    confidence_hint: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    strategy_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategies.id", ondelete="SET NULL"), nullable=True
    )
    decision_history_id: Mapped[int | None] = mapped_column(
        ForeignKey("decision_histories.id", ondelete="SET NULL"), nullable=True
    )
    detected_at: Mapped[datetime] = mapped_column()
    processed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("ix_trading_events_event_type", "event_type"),
        Index("ix_trading_events_stock_code", "stock_code"),
        Index("ix_trading_events_status", "status"),
        Index("ix_trading_events_detected_at", "detected_at"),
        Index("ix_trading_events_stock_code_event_type_detected_at", "stock_code", "event_type", "detected_at"),
    )
