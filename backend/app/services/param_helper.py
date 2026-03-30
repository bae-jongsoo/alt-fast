"""시스템 파라미터 조회 헬퍼.

조회 우선순위: strategy_id별 값 → 글로벌(strategy_id=NULL) → 코드 기본값
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_parameter import SystemParameter


async def get_param(
    db: AsyncSession,
    key: str,
    default: str,
    strategy_id: int | None = None,
) -> str:
    """시스템 파라미터 조회. 전략별 → 글로벌 → 기본값 순."""
    if strategy_id is not None:
        result = await db.execute(
            select(SystemParameter.value).where(
                SystemParameter.key == key,
                SystemParameter.strategy_id == strategy_id,
            )
        )
        val = result.scalar_one_or_none()
        if val is not None:
            return val

    # 글로벌 (strategy_id IS NULL)
    result = await db.execute(
        select(SystemParameter.value).where(
            SystemParameter.key == key,
            SystemParameter.strategy_id.is_(None),
        )
    )
    val = result.scalar_one_or_none()
    if val is not None:
        return val

    return default
