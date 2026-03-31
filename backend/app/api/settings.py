from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.schemas.settings import (
    PromptTemplateItem,
    PromptTemplateListResponse,
    PromptTemplateUpdate,
    SystemParameterListResponse,
    SystemParameterUpdate,
    TargetStockCreate,
    TargetStockItem,
    TargetStockListResponse,
)
from app.services.settings import (
    create_stock,
    delete_stock,
    get_parameters,
    get_prompt_variables,
    get_prompts,
    get_stocks,
    reset_parameters,
    update_parameters,
    update_prompt,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


# ── 종목 설정 ──


@router.get("/stocks", response_model=TargetStockListResponse)
async def list_stocks(strategy_id: int | None = None, db: AsyncSession = Depends(get_db)):
    return await get_stocks(db, strategy_id)


@router.post("/stocks", response_model=TargetStockItem, status_code=201)
async def add_stock(
    data: TargetStockCreate,
    db: AsyncSession = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    return await create_stock(db, data, strategy_id=data.strategy_id)


@router.delete("/stocks/{stock_code}", status_code=204)
async def remove_stock(
    stock_code: str,
    strategy_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    await delete_stock(db, stock_code, strategy_id)


# ── 프롬프트 설정 ──


@router.get("/prompts", response_model=PromptTemplateListResponse)
async def list_prompts(strategy_id: int | None = None, db: AsyncSession = Depends(get_db)):
    return await get_prompts(db, strategy_id)


@router.put("/prompts/{prompt_type}", response_model=PromptTemplateItem)
async def edit_prompt(
    prompt_type: str,
    data: PromptTemplateUpdate,
    strategy_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    return await update_prompt(db, prompt_type, data, strategy_id)


@router.get("/prompts/variables")
async def list_prompt_variables():
    return get_prompt_variables()


# ── 시스템 파라미터 ──


@router.get("/parameters", response_model=SystemParameterListResponse)
async def list_parameters(strategy_id: int | None = None, db: AsyncSession = Depends(get_db)):
    return await get_parameters(db, strategy_id=strategy_id)


@router.put("/parameters", response_model=SystemParameterListResponse)
async def edit_parameters(
    data: SystemParameterUpdate,
    db: AsyncSession = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    return await update_parameters(db, data)


@router.post("/parameters/reset", response_model=SystemParameterListResponse)
async def reset_all_parameters(
    db: AsyncSession = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    return await reset_parameters(db)
