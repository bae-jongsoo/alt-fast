import re
from datetime import datetime

from pydantic import BaseModel, field_validator


# --- 종목 설정 ---
class TargetStockItem(BaseModel):
    id: int
    stock_code: str
    stock_name: str
    dart_corp_code: str | None
    is_active: bool
    created_at: datetime


class TargetStockCreate(BaseModel):
    strategy_id: int
    stock_code: str
    stock_name: str
    dart_corp_code: str | None = None

    @field_validator("stock_code")
    @classmethod
    def validate_stock_code(cls, v: str) -> str:
        if not re.match(r"^\d{6}$", v):
            raise ValueError("종목코드는 6자리 숫자여야 합니다.")
        return v


class TargetStockListResponse(BaseModel):
    items: list[TargetStockItem]


# --- 프롬프트 설정 ---
class PromptTemplateItem(BaseModel):
    id: int
    prompt_type: str
    content: str
    version: int
    is_active: bool
    created_at: datetime


class PromptTemplateUpdate(BaseModel):
    content: str


class PromptTemplateListResponse(BaseModel):
    buy_prompt: PromptTemplateItem | None
    sell_prompt: PromptTemplateItem | None
    buy_versions: list[PromptTemplateItem]
    sell_versions: list[PromptTemplateItem]


# --- 시스템 파라미터 ---
class SystemParameterItem(BaseModel):
    key: str
    value: str
    updated_at: datetime


class SystemParameterUpdate(BaseModel):
    parameters: dict[str, str]


class SystemParameterListResponse(BaseModel):
    items: list[SystemParameterItem]
