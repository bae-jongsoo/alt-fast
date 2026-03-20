from datetime import datetime, timedelta

MAX_ATTEMPTS = 5
BLOCK_DURATION = timedelta(minutes=5)

_login_attempts: dict[str, dict] = {}


def is_blocked(ip: str) -> bool:
    record = _login_attempts.get(ip)
    if not record:
        return False
    blocked_until = record.get("blocked_until")
    if blocked_until and datetime.utcnow() < blocked_until:
        return True
    if blocked_until and datetime.utcnow() >= blocked_until:
        _login_attempts.pop(ip, None)
        return False
    return False


def record_failure(ip: str) -> None:
    record = _login_attempts.setdefault(ip, {"count": 0, "blocked_until": None})
    record["count"] += 1
    if record["count"] >= MAX_ATTEMPTS:
        record["blocked_until"] = datetime.utcnow() + BLOCK_DURATION


def record_success(ip: str) -> None:
    _login_attempts.pop(ip, None)
