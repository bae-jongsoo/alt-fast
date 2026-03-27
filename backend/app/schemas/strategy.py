from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class StrategyItem(BaseModel):
    id: int
    name: str
    description: str | None
    initial_capital: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime


class StrategyCreate(BaseModel):
    name: str
    description: str | None = None
    initial_capital: Decimal


class StrategyUpdate(BaseModel):
    description: str | None = None
    is_active: bool | None = None


class StrategyListResponse(BaseModel):
    items: list[StrategyItem]
