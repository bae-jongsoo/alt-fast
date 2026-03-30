"""매크로 데이터 API 엔드포인트."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.macro_snapshot import MacroSnapshot
from app.schemas.macro import MacroSnapshotResponse

router = APIRouter(prefix="/api/macro", tags=["macro"])


@router.get("/latest", response_model=MacroSnapshotResponse | None)
async def get_latest_macro(
    db: AsyncSession = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    """최신 매크로 스냅샷 조회."""
    result = await db.execute(
        select(MacroSnapshot).order_by(MacroSnapshot.snapshot_date.desc()).limit(1)
    )
    snapshot = result.scalar_one_or_none()
    if snapshot is None:
        return None
    return MacroSnapshotResponse.model_validate(snapshot)
