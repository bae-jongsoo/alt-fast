from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SystemParameter(Base):
    __tablename__ = "system_parameters"
    __table_args__ = (
        UniqueConstraint("key", "strategy_id", name="uq_system_parameters_key_strategy"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), index=True)
    value: Mapped[str] = mapped_column(String(500))
    strategy_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("strategies.id", ondelete="CASCADE"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
