import hashlib
import hmac
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request

from prospector.store.mail import MailRepo

MAX_BODY = 5 * 1024 * 1024
MAX_SKEW_SECONDS = 300


def sign(secret: bytes, timestamp: str, body: bytes) -> str:
    """Hex HMAC-SHA256 over `<timestamp>.<body>` (mirrored in mail-bridge/src/sign.ts)."""
    return hmac.new(secret, timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def verify_signature(secret: bytes, headers, body: bytes, now: datetime) -> bool:
    ts, sig = headers.get("x-prospector-timestamp"), headers.get("x-prospector-signature", "")
    if not ts or not sig.startswith("sha256="):
        return False
    try:
        skew = abs(now.timestamp() - int(ts))
    except ValueError:
        return False
    return skew <= MAX_SKEW_SECONDS and hmac.compare_digest(sig[7:], sign(secret, ts, body))


def make_ingest_router(mail: MailRepo, secret: bytes,
                       clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> APIRouter:
    router = APIRouter()

    @router.post("/ingest/mail", status_code=202)
    async def ingest_mail(request: Request):
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_BODY:
            raise HTTPException(413, "too large")
        body = await request.body()
        if len(body) > MAX_BODY:
            raise HTTPException(413, "too large")
        now = clock()
        if not verify_signature(secret, request.headers, body, now):
            raise HTTPException(401, "bad signature")
        return {"id": mail.insert(body, now)}

    return router
