from datetime import datetime

from sqlalchemy import Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class News(Base):
    __tablename__ = "news"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(32))
    stock_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    external_id: Mapped[str] = mapped_column(String(128), unique=True)
    link: Mapped[str] = mapped_column(String(2048), default="")
    title: Mapped[str] = mapped_column(String(255), default="")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    useful: Mapped[bool | None] = mapped_column(nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("ix_news_stock_code", "stock_code"),
        Index("ix_news_created_at", "created_at"),
        Index("ix_news_published_at", "published_at"),
        Index("ix_news_stock_code_published_at", "stock_code", "published_at"),
        Index("ix_news_stock_code_created_at", "stock_code", "created_at"),
        Index("ix_news_stock_code_useful_created_at", "stock_code", "useful", "created_at"),
    )
