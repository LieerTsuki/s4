"""Versioned bulk preflight and controlled original JSONL ingestion."""
import asyncio
import base64
import binascii
import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from ..schemas import StrictModel
from ..security import Actor, ApiError, Db, require_role
from ..services.common import audit
from ..services.ingress_v13 import parse_jsonl, preflight
from ..services.workflow_v13 import store_for

router = APIRouter()


class JsonlUploadV2(StrictModel):
    envelope: dict[str, Any]
    file_base64: str = Field(max_length=27_000_000)


@router.post("/imports/validate")
async def validate_import(body: dict[str, Any], request: Request, actor: Actor) -> dict[str, Any]:
    require_role(actor, "lead")
    if len(json.dumps(body, ensure_ascii=False).encode()) > request.app.state.settings.max_import_bytes:
        raise ApiError(413, "IMPORT_TOO_LARGE", "导入材料超过允许大小")
    return await asyncio.to_thread(preflight, body)


@router.post("/imports/upload", status_code=201)
async def upload(body: JsonlUploadV2, request: Request, actor: Actor, db: Db) -> Any:
    require_role(actor, "lead")
    try:
        raw = base64.b64decode(body.file_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ApiError(422, "UPLOAD_ENCODING_INVALID", "原始文件编码无效") from exc
    payload, report = await asyncio.to_thread(parse_jsonl, raw, body.envelope, request.app.state.settings.max_import_bytes)
    if payload is None:
        return JSONResponse(status_code=422, content={"error_code": "IMPORT_VALIDATION_FAILED", "message": "文件或批次校验失败，请核对逐行错误",
                                                     "validation_report": report, "request_id": request.state.request_id})
    from .v13 import create_import
    result = await create_import(payload, request, actor, db)
    raw_ref = await asyncio.to_thread(store_for(request).put_json, {"encoding": "base64", "file_base64": body.file_base64,
                                         "raw_file_sha256": report["raw_file_sha256"]})
    audit(db, request, actor.id, "V13_IMPORT_FILE_UPLOADED", result["id"],
          {"raw_file_ref": raw_ref, "raw_file_sha256": report["raw_file_sha256"], "rows": report["total_rows"]})
    return {**result, "validation_report": report, "raw_file_sha256": report["raw_file_sha256"]}
