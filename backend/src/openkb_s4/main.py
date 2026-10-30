"""FastAPI entry point with safe errors and database-backed request transactions."""
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .config import Settings, get_settings
from .db import make_sessions
from .domain.errors import DomainError
from .models import AuditEvent, Heartbeat, now
from .security import ApiError
from .services.content_store import ContentStoreError

logger = logging.getLogger("openkb_s4")
PREFIX = "/api/s4/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an app without creating tables or touching production materials."""
    configuration = settings or get_settings()
    engine, sessions = make_sessions(configuration.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    application = FastAPI(title="OpenKB-Eval S4", version="0.1.0", lifespan=lifespan,
                          docs_url=f"{PREFIX}/docs", openapi_url=f"{PREFIX}/openapi.json")
    application.state.settings = configuration
    application.state.engine = engine
    application.state.sessions = sessions

    @application.middleware("http")
    async def request_context(request: Request, call_next: Any) -> Any:
        request.state.request_id = str(uuid4())
        if (not configuration.legacy_writes_enabled
                and request.method not in {"GET", "HEAD", "OPTIONS"}
                and request.url.path.startswith(PREFIX + "/")
                and not request.url.path.startswith((PREFIX + "/auth/", PREFIX + "/users"))):
            response = error_response(request, 409, "LEGACY_READ_ONLY", "历史流程只读，请使用v1.3核实与观测入口")
            response.headers["X-Request-ID"] = request.state.request_id
            response.headers["Cache-Control"] = "no-store"
            return response
        try:
            response = await call_next(request)
        except Exception:
            # Database/IO exceptions may carry SQL parameters and raw task material.
            # Keep ordinary logs limited to the opaque request identifier.
            logger.error('{"event":"request_failed","request_id":"%s"}', request.state.request_id)
            response = error_response(request, 500, "INTERNAL_ERROR", "服务暂时无法完成请求，请凭请求编号联系运营")
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        if response.status_code in {401, 403, 404} and request.url.path.startswith("/api/s4/"):
            try:
                async with sessions() as db, db.begin():
                    db.add(AuditEvent(actor_id=getattr(request.state, "actor_id", None), action="ACCESS_DENIED",
                                      object_id=None, request_id=request.state.request_id,
                                      details={"status": response.status_code, "method": request.method}))
            except Exception:
                logger.error('{"event":"audit_write_failed","request_id":"%s"}', request.state.request_id)
        return response

    def error_response(request: Request, status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(status_code=status, content={"error_code": code, "message": message,
                            "request_id": getattr(request.state, "request_id", "unknown")})

    @application.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(request, exc.status, exc.code, exc.message)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, _: RequestValidationError) -> JSONResponse:
        return error_response(request, 422, "INPUT_INVALID", "字段格式或取值无效，请检查必填项和规定枚举")

    @application.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return error_response(request, 422, exc.code, exc.message)

    @application.exception_handler(ContentStoreError)
    async def content_error(request: Request, _: ContentStoreError) -> JSONResponse:
        return error_response(request, 409, "CONTROLLED_OBJECT_INVALID", "受控材料缺失或摘要不一致，请暂停并联系运营")

    @application.exception_handler(IntegrityError)
    async def conflict_error(request: Request, _: IntegrityError) -> JSONResponse:
        return error_response(request, 409, "UNIQUE_CONFLICT", "记录已存在或与当前约束冲突")

    @application.get(f"{PREFIX}/health/live")
    @application.get("/api/s4/v2/health/live")
    async def live() -> dict[str, str]:
        return {"status": "alive"}

    @application.get(f"{PREFIX}/health/ready")
    @application.get("/api/s4/v2/health/ready")
    async def ready() -> Any:
        try:
            async with sessions() as db:
                revision = await db.scalar(text("SELECT version_num FROM alembic_version"))
                heartbeat = await db.get(Heartbeat, "worker")
                worker_ready = heartbeat is not None and now() - heartbeat.at < timedelta(seconds=90)
                db_ready = revision == "0006_v13"
                data = {"status": "ready" if db_ready and worker_ready else "not_ready", "database": db_ready,
                        "migration": revision, "worker": worker_ready, "external_alignment": "NOT_ALIGNED"}
                return JSONResponse(status_code=200 if db_ready and worker_ready else 503, content=data)
        except Exception:
            return JSONResponse(status_code=503, content={"status": "not_ready", "database": False, "worker": False})

    # Resource routers are imported here so tools can import configuration independently.
    from .api import auth, exports, governance, operations, quality, workflow
    for router in (auth.router, workflow.router, quality.router, exports.router, governance.router, operations.router):
        application.include_router(router, prefix=PREFIX)
    from .api import handoffs_v13, ingress_v13, v13
    for router in (ingress_v13.router, v13.router, handoffs_v13.router):
        application.include_router(router, prefix="/api/s4/v2")
    return application


app = create_app()
