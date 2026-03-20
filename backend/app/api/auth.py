from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import get_current_user
from app.schemas.auth import LoginRequest, TokenResponse, UserResponse
from app.services.auth import create_access_token, verify_credentials
from app.services.rate_limit import is_blocked, record_failure, record_success

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"

    if is_blocked(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="잠시 후 다시 시도해주세요.",
        )

    if not verify_credentials(body.login_id, body.password):
        record_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 올바르지 않습니다",
        )

    record_success(client_ip)
    token = create_access_token(body.login_id)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def me(current_user: str = Depends(get_current_user)):
    return UserResponse(login_id=current_user)
