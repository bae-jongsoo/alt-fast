from datetime import datetime

from sqlalchemy import ForeignKey, Index, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DecisionHistory(Base):
    __tablename__ = "decision_histories"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_id: Mapped[int] = mapped_column(
        ForeignKey("strategies.id", ondelete="RESTRICT")
    )
    stock_code: Mapped[str] = mapped_column(String(6))
    stock_name: Mapped[str] = mapped_column(String(50))
    decision: Mapped[str] = mapped_column(String(16), default="HOLD")
    request_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_decision: Mapped[dict | None] = mapped_column(JSON, default=dict, nullable=True)
    processing_time_ms: Mapped[int] = mapped_column(default=0)
    is_error: Mapped[bool] = mapped_column(default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("ix_decision_histories_strategy_id_created_at", "strategy_id", "created_at"),
        Index("ix_decision_histories_decision", "decision"),
        Index("ix_decision_histories_created_at", "created_at"),
        Index("ix_decision_histories_is_error_created_at", "is_error", "created_at"),
    )
