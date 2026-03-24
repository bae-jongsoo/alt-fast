from datetime import datetime

from pydantic import BaseModel


class OrderHistoryItem(BaseModel):
    id: int
    created_at: datetime
    stock_code: str
    stock_name: str
    order_type: str
    order_price: float
    quantity: int
    total_amount: float
    profit_loss: float | None
    profit_rate: float | None
    profit_rate_net: float | None
    decision_history_id: int | None


class OrderHistoryListResponse(BaseModel):
    items: list[OrderHistoryItem]
    total: int
    page: int
    page_size: int


class SourceItem(BaseModel):
    type: str
    weight: float
    detail: str = ""


class DecisionHistoryItem(BaseModel):
    id: int
    created_at: datetime
    stock_code: str
    stock_name: str
    decision: str
    is_error: bool
    error_message: str | None
    sources: list[SourceItem] | None = None


class DecisionDetailResponse(BaseModel):
    id: int
    created_at: datetime
    stock_code: str
    stock_name: str
    decision: str
    request_payload: str | None
    response_payload: str | None
    parsed_decision: dict | None
    is_error: bool
    error_message: str | None
    linked_order: OrderHistoryItem | None


class DecisionHistoryListResponse(BaseModel):
    items: list[DecisionHistoryItem]
    total: int
    page: int
    page_size: int
