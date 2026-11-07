"""v1.3 profile approvals preserve external blockers and frozen history."""
from copy import deepcopy
from pathlib import Path

import pytest

from openkb_s4.domain.errors import DomainError


def test_v13_templates_cover_thirteen_datasets_without_inventing_vocabularies():
    from openkb_s4.domain.profiles_v13 import template, validate_snapshot
    from openkb_s4.domain.v13 import QUOTAS

    for dataset, quota in QUOTAS.items():
        snapshot = template(dataset)
        validate_snapshot(dataset, snapshot)
        assert snapshot["quota"] == quota
        assert snapshot["formal_enabled"] is False
        assert snapshot["vocabulary"]["status"] == "UNCONFIRMED"
        assert snapshot["blocked_reasons"]


def test_template_phase_projection_matches_the_executed_blind_allowlist():
    from openkb_s4.domain.profiles_v13 import template
    from openkb_s4.services.workflow_v13 import BLIND_FIELDS

    assert set(template("QA-D1")["blind_fields"]) == BLIND_FIELDS | {"contexts"}


def test_immutable_scale_uses_json_types_not_python_boolean_numeric_equality():
    from openkb_s4.domain.profiles_v13 import template, validate_snapshot

    snapshot = template("QA-D1")
    snapshot["evidence_labels"] = [False, True, 2, 3]
    with pytest.raises(DomainError):
        validate_snapshot("QA-D1", snapshot)


@pytest.mark.parametrize("field,value", [
    ("formal_enabled", True), ("review_version", "openkb.s4-review.v2"),
    ("point_labels", ["good", "bad"]), ("blocked_reasons", []),
    ("vocabulary", {"status": "APPROVED", "entity_types": ["FAKE"]}),
    ("input_schema", {"exec": "python"}),
])
def test_v13_profile_cannot_unlock_external_rules_or_change_core(field, value):
    from openkb_s4.domain.profiles_v13 import template, validate_snapshot

    snapshot = template("QA-D6")
    snapshot[field] = value
    with pytest.raises(DomainError, match="核心|字段"):
        validate_snapshot("QA-D6", snapshot)


def test_v13_profile_accepts_manual_text_and_versions_but_rejects_injected_fields():
    from openkb_s4.domain.profiles_v13 import template, validate_snapshot

    snapshot = template("QA-D1")
    snapshot.update(version="trial-2", manual_version="manual-2", manual_text="待批准的本地补充说明")
    validate_snapshot("QA-D1", snapshot)
    changed = deepcopy(snapshot)
    changed["script"] = "run()"
    with pytest.raises(DomainError):
        validate_snapshot("QA-D1", changed)


def test_approval_rejects_same_real_person_even_when_account_differs():
    from openkb_s4.domain.profiles_v13 import transition

    with pytest.raises(DomainError) as error:
        transition("REVIEW", "approve", 2, 2, "human-1", ["human-1"], ["auditor"], "署名", {"basis": "review"})
    assert error.value.code == "INDEPENDENT_APPROVAL_REQUIRED"


@pytest.mark.parametrize("state,action,revision,expected,roles,signature,evidence,code", [
    ("DRAFT", "submit", 2, 1, ["lead"], "", {}, "VERSION_CONFLICT"),
    ("APPROVED", "submit", 2, 2, ["lead"], "", {}, "PROFILE_TRANSITION_INVALID"),
    ("REVIEW", "approve", 2, 2, ["lead"], "署名", {"basis": "x"}, "FORBIDDEN"),
    ("REVIEW", "approve", 2, 2, ["auditor"], "", {"basis": "x"}, "APPROVAL_EVIDENCE_REQUIRED"),
    ("REVIEW", "approve", 2, 2, ["auditor"], "署名", {}, "APPROVAL_EVIDENCE_REQUIRED"),
])
def test_transition_guards(state, action, revision, expected, roles, signature, evidence, code):
    from openkb_s4.domain.profiles_v13 import transition

    with pytest.raises(DomainError) as error:
        transition(state, action, revision, expected, "auditor-person", ["creator-person"], roles, signature, evidence)
    assert error.value.code == code


def test_lifecycle_is_explicit_and_retirement_does_not_rewrite_snapshot():
    from openkb_s4.domain.profiles_v13 import transition

    assert transition("DRAFT", "submit", 1, 1, "creator", ["creator"], ["lead"], "", {}) == "REVIEW"
    assert transition("REVIEW", "approve", 2, 2, "auditor", ["creator"], ["auditor"], "署名", {"basis": "x"}) == "APPROVED"
    assert transition("APPROVED", "retire", 3, 3, "creator", ["creator"], ["lead"], "", {}) == "RETIRED"


@pytest.mark.parametrize("drift", ["review_schema", "specialized_fields", "none"])
def test_frozen_snapshot_rejects_runtime_core_drift_but_allows_retired_history(tmp_path: Path, monkeypatch, drift):
    from openkb_s4.domain.contracts import canonical_sha256
    from openkb_s4.domain.profiles_v13 import template
    from openkb_s4.domain.v13 import SPECIALIZED_FIELDS, ReviewV3
    from openkb_s4.models_v13 import V13Batch
    from openkb_s4.security import ApiError
    from openkb_s4.services.content_store import ContentStore
    from openkb_s4.services.workflow_v13 import frozen_profile_snapshot

    store = ContentStore(tmp_path)
    snapshot = template("QA-D6")
    snapshot_ref = store.put_json(snapshot)
    digest = canonical_sha256(snapshot)
    batch = V13Batch(dataset="QA-D6", profile_version=snapshot["version"],
                     manual_version=snapshot["manual_version"], profile_hash=digest,
                     profile_snapshot_ref=snapshot_ref,
                     profile_approval_ref=store.put_json({"canonical_hash": digest, "snapshot_ref": snapshot_ref}),
                     manual_ref=store.put_json({"version": snapshot["manual_version"], "text": snapshot["manual_text"]}),
                     vocabulary_ref=store.put_json(snapshot["vocabulary"]))
    if drift == "review_schema":
        monkeypatch.setattr(ReviewV3, "model_json_schema", lambda: {"type": "object", "changed": True})
    elif drift == "specialized_fields":
        monkeypatch.setitem(SPECIALIZED_FIELDS, "QA-D6", ["changed_runtime_core"])
    else:
        # Frozen reads do not inspect the profile's live APPROVED/RETIRED state.
        assert frozen_profile_snapshot(batch, store) == snapshot
        return
    with pytest.raises(ApiError) as error:
        frozen_profile_snapshot(batch, store)
    assert error.value.status == 409
    assert error.value.code == "FROZEN_PROFILE_CONFLICT"
