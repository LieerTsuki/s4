"""Local account sessions, password hashing and persisted login throttling."""

import secrets
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from ..models import LoginRate, Session, User, now
from ..schemas import Login, UserCreate, UserUpdate
from ..security import (
    Actor,
    ApiError,
    Db,
    check_password,
    digest,
    expiry,
    hash_password,
    require_role,
    user_view,
)
from ..services.common import audit

router = APIRouter()


@router.post("/auth/login")
async def login(body: Login, request: Request, response: Response, db: Db) -> dict[str, Any]:
    origin = request.headers.get("origin")
    allowed = request.app.state.settings.allowed_origin or str(request.base_url).rstrip("/")
    if origin and origin != allowed:
        raise ApiError(403, "ORIGIN_REJECTED", "请求来源不允许")
    key = digest(
        f"{request.client.host if request.client else 'unknown'}:{body.username.casefold()}"
    )
    await db.execute(
        insert(LoginRate).values(key=key, count=0, window_start=now()).on_conflict_do_nothing()
    )
    rate = await db.scalar(select(LoginRate).where(LoginRate.key == key).with_for_update())
    assert rate is not None
    if now() - rate.window_start > timedelta(minutes=15):
        rate.count, rate.window_start = 0, now()
    if rate.count >= request.app.state.settings.login_limit:
        raise ApiError(429, "LOGIN_RATE_LIMIT", "尝试次数过多，请稍后再试")
    user = await db.scalar(select(User).where(User.username == body.username))
    if not user or not user.active or not check_password(user.password_hash, body.password):
        rate.count += 1
        audit(db, request, None, "LOGIN_FAILED", None)
        await db.commit()
        raise ApiError(401, "INVALID_CREDENTIALS", "账号或密码不正确")
    rate.count = 0
    token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    db.add(
        Session(
            user_id=user.id,
            token_hash=digest(token),
            csrf_hash=digest(csrf),
            csrf_token=csrf,
            expires_at=expiry(request.app.state.settings.session_hours),
        )
    )
    response.set_cookie(
        "s4_session",
        token,
        httponly=True,
        secure=request.app.state.settings.cookie_secure,
        samesite="strict",
        max_age=request.app.state.settings.session_hours * 3600,
        path="/",
    )
    audit(db, request, user.id, "LOGIN_SUCCESS", user.id)
    return {"user": user_view(user), "csrf_token": csrf}


@router.get("/auth/me")
async def me(request: Request, actor: Actor) -> dict[str, Any]:
    return {"user": user_view(actor), "csrf_token": request.state.auth_session.csrf_token}


@router.post("/auth/logout")
async def logout(request: Request, response: Response, actor: Actor, db: Db) -> dict[str, bool]:
    request.state.auth_session.revoked = True
    response.delete_cookie("s4_session", path="/")
    audit(db, request, actor.id, "LOGOUT", actor.id)
    return {"ok": True}


@router.get("/users")
async def users(
    actor: Actor, db: Db, offset: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=500)
) -> dict[str, Any]:
    require_role(actor, "admin", "lead")
    rows = (
        await db.scalars(
            select(User).order_by(User.created_at, User.id).offset(offset).limit(limit)
        )
    ).all()
    return {
        "items": [user_view(user) for user in rows],
        "total": await db.scalar(select(func.count()).select_from(User)),
        "offset": offset,
        "limit": limit,
    }


@router.post("/users", status_code=201)
async def create_user(body: UserCreate, request: Request, actor: Actor, db: Db) -> dict[str, Any]:
    require_role(actor, "admin")
    user = User(
        username=body.username,
        display_name=body.display_name,
        person_id=body.person_id,
        roles=list(dict.fromkeys(body.roles)),
        password_hash=hash_password(body.password),
    )
    db.add(user)
    await db.flush()
    audit(db, request, actor.id, "USER_CREATED", user.id, {"roles": user.roles})
    return user_view(user)


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str, body: UserUpdate, request: Request, actor: Actor, db: Db
) -> dict[str, Any]:
    require_role(actor, "admin")
    user = await db.get(User, user_id)
    if not user:
        raise ApiError(404, "NOT_FOUND", "账号不存在")
    if user.id == actor.id and (
        body.active is False or (body.roles is not None and "admin" not in body.roles)
    ):
        raise ApiError(409, "SELF_ADMIN_LOCKOUT", "不能移除当前管理员本人的管理权限")
    if body.active is not None:
        user.active = body.active
    if body.roles is not None:
        user.roles = list(dict.fromkeys(body.roles))
    if body.password:
        user.password_hash = hash_password(body.password)
    await db.execute(update(Session).where(Session.user_id == user.id).values(revoked=True))
    audit(
        db, request, actor.id, "USER_UPDATED", user.id, {"active": user.active, "roles": user.roles}
    )
    return user_view(user)
