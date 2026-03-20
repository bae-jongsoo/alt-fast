from datetime import datetime

from pydantic import BaseModel


class NewsItem(BaseModel):
    id: int
    stock_code: str
    stock_name: str
    title: str
    summary: str | None
    url: str
    useful: bool | None
    published_at: datetime | None


class NewsListResponse(BaseModel):
    items: list[NewsItem]
    total: int
    page: int
    page_size: int


class DartItem(BaseModel):
    id: int
    stock_code: str
    stock_name: str
    title: str
    description: str | None
    rcept_no: str
    url: str | None
    published_at: datetime | None


class DartListResponse(BaseModel):
    items: list[DartItem]
    total: int
    page: int
    page_size: int
