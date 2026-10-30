"""Bulk preflight preserves original bytes and reports independent row errors."""
import json
from copy import deepcopy
from pathlib import Path

import pytest


def source() -> dict:
    path = Path(__file__).resolve().parents[2] / "contracts/v13/examples/demo-import.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_bulk_preflight_reports_all_rows_without_raw_material_in_errors() -> None:
    from openkb_s4.services.ingress_v13 import preflight

    payload = source()
    payload["units"] = [deepcopy(payload["units"][0]), deepcopy(payload["units"][0])]
    payload["units"][0]["difficulty"] = "简单"
    payload["units"][1]["unit_id"] = "QA-D1-second"
    payload["units"][1]["gold"]["expected_refusal"] = "false"
    report = preflight(payload)
    assert not report["valid"] and {error["row"] for error in report["errors"]} == {1, 2}
    assert "question" not in str(report["errors"])


def test_jsonl_keeps_original_utf8_bom_crlf_and_decoded_unit_set() -> None:
    from openkb_s4.services.ingress_v13 import parse_jsonl

    payload = source()
    envelope = {key: value for key, value in payload.items() if key != "units"}
    raw = b"\xef\xbb\xbf" + b"\r\n".join(json.dumps(unit, ensure_ascii=False).encode() for unit in payload["units"]) + b"\r\n"
    parsed, report = parse_jsonl(raw, envelope)
    assert report["valid"]
    assert parsed["units"] == payload["units"]
    import hashlib
    assert report["raw_file_sha256"] == hashlib.sha256(raw).hexdigest()


def test_jsonl_syntax_errors_have_actual_line_numbers() -> None:
    from openkb_s4.services.ingress_v13 import parse_jsonl

    payload, report = parse_jsonl(b'{"unit_id":"u"}\n\nnot-json\n[1,2]\n', {"mode": "demo"})
    assert payload is None and not report["valid"]
    assert {error["row"] for error in report["errors"]} == {3, 4}


@pytest.mark.parametrize("raw", [b"\xff", b"", b"\n\n"])
def test_bad_utf8_or_empty_input_is_rejected(raw: bytes) -> None:
    from openkb_s4.services.ingress_v13 import parse_jsonl

    assert parse_jsonl(raw, {})[1]["valid"] is False


def test_jsonl_envelope_cannot_override_units_or_supply_external_paths() -> None:
    from openkb_s4.services.ingress_v13 import parse_jsonl

    payload = source()
    envelope = {key: value for key, value in payload.items() if key != "units"}
    raw = json.dumps(payload["units"][0]).encode()
    assert parse_jsonl(raw, {**envelope, "units": []})[1]["valid"] is False
    assert parse_jsonl(raw, {**envelope, "file_path": "C:/private/file"})[1]["valid"] is False
