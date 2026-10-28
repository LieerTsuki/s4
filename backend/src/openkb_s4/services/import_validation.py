"""Bounded row diagnostics using the same domain checks as the import transaction."""
from typing import Any

from ..domain.contracts import _validate_formal, _validate_unit, validate_import
from ..domain.errors import DomainError


def validate_import_report(payload: dict[str, Any], *, max_errors: int = 100) -> dict[str, Any]:
    """Report one domain error per invalid row plus independent package evidence errors.

    Diagnostics contain schema paths only, never the rejected material/value. A
    capped report still counts all invalid rows and explicitly marks truncation.
    """
    if max_errors < 1:
        raise ValueError("max_errors must be positive")
    errors: list[dict[str, Any]] = []
    units = payload.get("units", [])
    rows = units if isinstance(units, list) else []

    def issue(exc: DomainError, row: int, unit_id: str | None = None) -> None:
        field = exc.message.partition("：")[2].removesuffix("。") or "payload"
        # Domain validators only emit fixed field names; do not pass free-form
        # failure text from another layer into job results.
        path = field if field.isascii() and len(field) < 160 else "payload"
        details: dict[str, Any] = {"row": row, "field_path": path, "error_code": exc.code, "message": "输入字段或关联证据不符合契约"}
        if unit_id and len(unit_id) <= 160 and all(char.isalnum() or char in "-_.:" for char in unit_id):
            details["unit_id"] = unit_id
        errors.append(details)

    for index, raw in enumerate(rows, start=1):
        if not isinstance(raw, dict):
            issue(DomainError("INVALID_OBJECT", "输入契约字段无效或缺少证据：units。"), index)
            continue
        try:
            _validate_unit(raw, payload.get("mode") == "formal")
        except DomainError as exc:
            issue(exc, index, raw.get("unit_id") if isinstance(raw.get("unit_id"), str) else None)
    if errors and payload.get("mode") == "formal":
        # Package evidence has its own row 0 diagnostics even when a material
        # row is invalid. Malformed row references are already recorded above;
        # they must not turn diagnostics into an internal worker failure.
        try:
            _validate_formal(payload, rows)
        except DomainError as exc:
            issue(exc, 0)
        except (KeyError, TypeError, AttributeError):
            pass
    try:
        normalized = validate_import(payload)
    except DomainError as exc:
        # The package validator may stop at the same invalid row; retain it once.
        if not any(error["error_code"] == exc.code for error in errors):
            issue(exc, 0)
        return {"valid": False, "total_rows": len(rows), "error_count": len(errors), "errors": errors[:max_errors], "truncated": len(errors) > max_errors}
    return {"valid": True, "total_rows": len(rows), "error_count": 0, "errors": [], "truncated": False, "normalized": normalized}
