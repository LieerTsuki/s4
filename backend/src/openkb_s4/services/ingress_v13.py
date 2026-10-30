"""Versioned bulk preflight and raw UTF-8 JSONL parsing without path access."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ..domain.errors import DomainError
from ..domain.v13 import validate_envelope, validate_unit


def _report(errors: list[dict[str, Any]], total: int) -> dict[str, Any]:
    return {"valid": not errors, "total_rows": total, "error_count": len(errors),
            "errors": errors[:200], "truncated": len(errors) > 200}


def preflight(payload: dict[str, Any]) -> dict[str, Any]:
    errors = []
    units = payload.get("units")
    if isinstance(units, list) and len(units) <= 10000:
        for number, unit in enumerate(units, 1):
            try:
                if not isinstance(unit, dict):
                    raise DomainError("UNIT_OBJECT_REQUIRED", "每行须为一个单元对象")
                validate_unit(unit)
            except DomainError as exc:
                errors.append({"row": number, "unit_id": unit.get("unit_id") if isinstance(unit, dict) else None,
                               "error_code": exc.code, "message": exc.message})
        if errors:
            return _report(errors, len(units))
    try:
        validate_envelope(payload)
    except DomainError as exc:
        errors.append({"row": 0, "unit_id": None, "error_code": exc.code, "message": exc.message})
    return _report(errors, len(units) if isinstance(units, list) else 0)


def parse_jsonl(raw: bytes, envelope: dict[str, Any], max_bytes: int = 20_000_000) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    digest = hashlib.sha256(raw).hexdigest()
    def rejected(code: str, message: str) -> tuple[None, dict[str, Any]]:
        return None, {**_report([{"row": 0, "unit_id": None, "error_code": code, "message": message}], 0), "raw_file_sha256": digest}
    if len(raw) > max_bytes:
        return rejected("IMPORT_TOO_LARGE", "原始文件超过允许大小")
    if "units" in envelope:
        return rejected("ENVELOPE_UNITS_FORBIDDEN", "JSONL元信息不得包含units，避免覆盖文件内容")
    try:
        source = raw.decode("utf-8-sig")
    except UnicodeError:
        return rejected("UTF8_REQUIRED", "文件须为UTF-8编码")
    units, lines, errors = [], [], []
    for number, line in enumerate(source.splitlines(), 1):
        if not line.strip():
            continue
        try:
            unit = json.loads(line)
            if not isinstance(unit, dict):
                raise ValueError("object required")
            units.append(unit)
            lines.append(number)
        except ValueError:
            errors.append({"row": number, "unit_id": None, "error_code": "JSONL_ROW_INVALID", "message": "该行不是有效单元JSON对象"})
        if len(units) > 10000:
            return rejected("TOO_MANY_UNITS", "单次导入最多10000单元")
    if errors:
        return None, {**_report(errors, len(units) + len(errors)), "raw_file_sha256": digest}
    if not units:
        return rejected("EMPTY_FILE", "文件没有有效单元行")
    payload = {**envelope, "units": units}
    report = preflight(payload)
    for error in report["errors"]:
        if error["row"]:
            error["row"] = lines[error["row"] - 1]
    report["raw_file_sha256"] = digest
    return payload if report["valid"] else None, report
