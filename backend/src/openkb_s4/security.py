"""Server-owned authentication, CSRF and object policy checks."""
import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Annotated, Any

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import database
from .models import AnnotationBatch, Session, User, now

PASSWORDS = PasswordHasher()
# Commit the request transaction before sending success or exposing cookies/jobs.
# Request-scoped yield cleanup happens after the response and permits stale reads.
Db = Annotated[AsyncSession, Depends(database, scope="function")]


class ApiError(Exception):
    """An authorized, safe API error without raw material or secret content."""
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status, self.code, self.message = status, code, message


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(value: str) -> str:
    return PASSWORDS.hash(value)


def check_password(encoded: str, value: str) -> bool:
    try:
        return PASSWORDS.verify(encoded, value)
    except VerificationError:
        return False


def user_view(user: User) -> dict[str, Any]:
    return {"id": user.id, "username": user.username, "display_name": user.display_name,
            "person_id": user.person_id, "roles": user.roles, "active": user.active}


def require_role(user: User, *roles: str) -> None:
    if not set(user.roles).intersection(roles):
        raise ApiError(403, "FORBIDDEN", "当前角色无此权限")


def require_independent(user: User, batch: AnnotationBatch) -> None:
    if user.id in (batch.annotator_a, batch.annotator_b):
        raise ApiError(403, "PARTICIPANT_RESTRICTED", "参标人员不能读取或操作本批受限结果")


async def current_user(request: Request, db: Db) -> User:
    token = request.cookies.get("s4_session", "")
    session = await db.scalar(select(Session).where(Session.token_hash == digest(token)))
    if not session or session.revoked or session.expires_at <= now():
        raise ApiError(401, "UNAUTHENTICATED", "请先登录")
    user = await db.get(User, session.user_id)
    if not user or not user.active:
        raise ApiError(401, "UNAUTHENTICATED", "会话已失效")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf = request.headers.get("X-CSRF-Token", "")
        if not csrf or not hmac.compare_digest(session.csrf_hash, digest(csrf)):
            raise ApiError(403, "CSRF_FAILED", "请求缺少有效CSRF凭据")
        origin = request.headers.get("origin")
        allowed = request.app.state.settings.allowed_origin or str(request.base_url).rstrip("/")
        if origin and origin != allowed:
            raise ApiError(403, "ORIGIN_REJECTED", "请求来源不允许")
    request.state.actor_id = user.id
    request.state.auth_session = session
    return user


Actor = Annotated[User, Depends(current_user)]


def expiry(hours: int) -> datetime:
    return now() + timedelta(hours=hours)
