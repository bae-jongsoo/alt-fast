from datetime import datetime

from pydantic import BaseModel


class SummaryCard(BaseModel):
    total_asset_value: float
    total_asset_change: float | None
    total_asset_change_rate: float | None
    cash_balance: float
    today_realized_pnl: float
    today_trade_count: int
    today_buy_count: int
    today_sell_count: int


class HoldingStock(BaseModel):
    stock_code: str
    stock_name: str
    quantity: int
    avg_buy_price: float
    current_price: float
    eval_pnl: float
    profit_rate: float
    profit_rate_net: float


class SystemStatus(BaseModel):
    name: str
    status: str
    last_active_at: datetime | None
    threshold_seconds: int


class TradingCycleSummary(BaseModel):
    total_decisions: int
    buy_count: int
    sell_count: int
    hold_count: int
    error_count: int


class RecentOrder(BaseModel):
    id: int
    created_at: datetime
    stock_name: str
    order_type: str
    order_price: float
    quantity: int
    profit_loss: float | None
    profit_rate: float | None
    profit_rate_net: float | None


class RecentError(BaseModel):
    id: int
    created_at: datetime
    error_message: str


class DashboardResponse(BaseModel):
    summary: SummaryCard
    holdings: list[HoldingStock]
    system_status: list[SystemStatus]
    trading_summary: TradingCycleSummary
    recent_orders: list[RecentOrder]
    recent_errors: list[RecentError]
    last_updated_at: datetime
