from datetime import datetime

from pydantic import BaseModel


class CandleItem(BaseModel):
    minute_at: datetime
    open: int
    high: int
    low: int
    close: int
    volume: int


class CandleListResponse(BaseModel):
    items: list[CandleItem]
