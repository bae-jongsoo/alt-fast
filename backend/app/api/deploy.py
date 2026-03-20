import hashlib
import hmac
import subprocess

from fastapi import APIRouter, Request, HTTPException

from app.config import settings

router = APIRouter(prefix="/api", tags=["deploy"])


def _verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/deploy")
async def deploy(request: Request):
    secret = settings.WEBHOOK_SECRET
    if not secret:
        raise HTTPException(500, "WEBHOOK_SECRET not configured")

    signature = request.headers.get("X-Hub-Signature-256", "")
    body = await request.body()

    if not _verify_signature(body, signature, secret):
        raise HTTPException(403, "Invalid signature")

    # 비동기로 배포 스크립트 실행 (응답은 바로 반환)
    subprocess.Popen(
        ["/Users/jongsoobae/workspace/alt-fast/scripts/deploy.sh"],
        stdout=open("/var/log/alt-fast/deploy.log", "a"),
        stderr=open("/var/log/alt-fast/deploy.err.log", "a"),
    )

    return {"status": "deploy started"}
