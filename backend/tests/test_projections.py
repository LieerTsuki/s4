"""Stage-specific whitelists keep task facts while hiding automatic conclusions."""
from openkb_s4.services.common import safe_material


def test_blind_retains_specialized_facts_but_hides_automatic_quality() -> None:
    unit = {"chunk": "original chunk", "quality_metrics": {"automated_pass": False}, "access_context": {"requester": "employee"}, "inject_plan": {"payload": "static attack text"}, "gold": {"secret": "draft"}, "expected_behavior": "reject", "metadata": {"confidence": 0.9}}
    material = safe_material(unit)
    assert material["chunk"] == "original chunk"
    assert material["access_context"] == unit["access_context"]
    assert material["inject_plan"] == unit["inject_plan"]
    assert not {"gold", "expected_behavior", "quality_metrics", "metadata"}.intersection(material)


def test_review_includes_frozen_automated_quality_as_auditable_material() -> None:
    unit = {"chunk": "original chunk", "quality_metrics": {"completeness": 0.8}}
    assert safe_material(unit, phase="REVIEW")["quality_metrics"] == unit["quality_metrics"]


def test_blind_keeps_context_validity_and_acl_needed_to_judge_answerability() -> None:
    doc = {"doc_id": "source", "text": "source passage", "valid_from": "2020-01-01T00:00:00Z", "valid_until": "2021-01-01T00:00:00Z", "version": "r1", "page": 2, "start": 10, "end": 24, "acl_context": {"group": "staff"}, "s3_conclusion": "do not expose"}
    context = safe_material({"contexts": [doc]})["contexts"][0]
    assert context["valid_until"] == "2021-01-01T00:00:00Z"
    assert context["acl_context"] == {"group": "staff"}
    assert context["version"] == "r1" and context["page"] == 2
    assert (context["start"], context["end"]) == (10, 24)
    assert "s3_conclusion" not in context
