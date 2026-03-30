from datetime import datetime

from sqlalchemy import Boolean, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class NewsCluster(Base):
    __tablename__ = "news_clusters"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(32))
    stock_name: Mapped[str] = mapped_column(String(50))
    cluster_type: Mapped[str] = mapped_column(String(20))  # "volume" or "theme"
    keyword: Mapped[str | None] = mapped_column(String(100), nullable=True)
    news_count: Mapped[int] = mapped_column(Integer, default=0)
    first_news_at: Mapped[datetime] = mapped_column()
    last_news_at: Mapped[datetime] = mapped_column()
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("ix_news_clusters_stock_code", "stock_code"),
        Index("ix_news_clusters_is_processed", "is_processed"),
        Index("ix_news_clusters_created_at", "created_at"),
    )
