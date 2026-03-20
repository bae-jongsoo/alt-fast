from datetime import datetime, timedelta

from jose import JWTError, jwt

from app.config import settings


def create_access_token(admin_id: str) -> str:
    payload = {
        "sub": admin_id,
        "exp": datetime.utcnow() + timedelta(hours=settings.JWT_EXPIRE_HOURS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def verify_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


def verify_credentials(login_id: str, password: str) -> bool:
    return login_id == settings.ADMIN_ID and password == settings.ADMIN_PW
