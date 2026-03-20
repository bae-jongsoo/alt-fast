from fastapi import Header, HTTPException, status

from app.services.auth import verify_token


async def get_current_user_optional(
    authorization: str | None = Header(None),
) -> str | None:
    if not authorization:
        return None
    token = authorization.removeprefix("Bearer ").strip()
    user = verify_token(token)
    return user


async def get_current_user(
    authorization: str = Header(...),
) -> str:
    token = authorization.removeprefix("Bearer ").strip()
    user = verify_token(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="세션이 만료되었습니다. 다시 로그인해주세요.",
        )
    return user
