"""Independent review regressions for cross-track exposure and revision bypasses."""
from copy import deepcopy
from typing import Any

import pytest
from helpers import login
from sqlalchemy import select
from test_v13_workflow import P, review, setup_v13, submit


def test_transitive_family_scope_covers_intermediate_unassigned_units() -> None:
    from openkb_s4.services.workflow_v13 import family_scope

    assert family_scope({"a"}, [["a", "b"], ["b", "c"], ["unrelated"]]) == {"a", "b", "c"}


@pytest.mark.asyncio
async def test_participant_operator_cannot_read_related_other_import_report(api: Any) -> None:
    from test_v13_workflow import source_payload

    from openkb_s4.models import User

    app, client, users, headers, first = await setup_v13(api)
    second = source_payload()
    second["batch_id"] = "V13-RELATED-SOURCE"
    for unit in second["units"]:
        unit["metadata"]["source_case_ids"] = ["QA-D1-v13-0"]
        unit["unit_id"] += "-related"
    created = await client.post(P + "/imports", headers=headers, json=second)
    assert created.status_code == 201, created.text
    async with app.state.sessions() as db, db.begin():
        actor = await db.get(User, users["v"])
        assert actor is not None
        actor.roles = ["lead", "annotator"]
    assigned = await client.post(P + "/verification-batches", headers=headers,
        json={"import_id": created.json()["id"], "dataset": "QA-D1", "assignee_ids": [users["v"]]})
    assert assigned.status_code == 201, assigned.text
    await login(client, "v")
    response = await client.get(P + f"/imports/{first}/report")
    assert response.status_code == 403
    assert (await client.get(P + "/imports")).json()["items"] == []


def test_d6_independent_projection_contains_original_fragment() -> None:
    from openkb_s4.services.workflow_v13 import split_unit

    fragment = {"unit_id": "QA-D6-1", "dataset": "QA-D6", "difficulty": "easy",
                "text": "😀原始片段", "gold": {"gold_entities": []}}
    blind, concealed = split_unit(fragment)
    assert blind["text"] == fragment["text"]
    assert "gold" not in blind and "gold" in concealed


@pytest.mark.asyncio
async def test_participant_lead_cannot_list_other_track_of_same_source(api: Any) -> None:
    from openkb_s4.models import User

    app, client, users, headers, imported = await setup_v13(api)
    async with app.state.sessions() as db, db.begin():
        user = await db.get(User, users["v"])
        assert user is not None
        user.roles = ["lead", "annotator"]
    created = await client.post(P + "/verification-batches", headers=headers,
        json={"import_id": imported, "dataset": "QA-D1", "assignee_ids": [users["v"]]})
    assert created.status_code == 201, created.text
    observed = await client.post(P + "/observation-batches", headers=headers,
        json={"import_id": imported, "dataset": "QA-D1", "annotator_a": users["a"], "annotator_b": users["b"]})
    assert observed.status_code == 201, observed.text
    await login(client, "v")
    result = await client.get(P + "/observation-batches")
    assert result.status_code == 200
    assert result.json()["items"] == []


@pytest.mark.asyncio
async def test_observer_cannot_open_primary_gold_before_own_observation_blind(api: Any) -> None:
    _, client, users, headers, imported = await setup_v13(api)
    observed = await client.post(P + "/observation-batches", headers=headers,
        json={"import_id": imported, "dataset": "QA-D1", "annotator_a": users["a"], "annotator_b": users["b"]})
    assert observed.status_code == 201, observed.text
    main = await client.post(P + "/verification-batches", headers=headers,
        json={"import_id": imported, "dataset": "QA-D1", "assignee_ids": [users["a"]]})
    if main.status_code in {403, 409, 422}:
        return
    assert main.status_code == 201, main.text
    headers = await login(client, "a")
    tasks = (await client.get(P + "/me/tasks")).json()["items"]
    observed_ids = {task["unit_id"] for task in tasks if task["workflow_kind"] == "OBSERVATION"}
    target = next(task for task in tasks if task["workflow_kind"] == "VERIFICATION" and task["unit_id"] in observed_ids)
    result = await submit(client, headers, target, {"answer": "本人独立判断", "reason": "原始材料"})
    assert result.status_code == 200, result.text
    detail = await client.get(P + f"/assignments/{target['id']}")
    assert detail.status_code == 409 or "gold" not in detail.json()


@pytest.mark.asyncio
async def test_revision_cannot_replace_missing_primary_independent_workflow(api: Any) -> None:
    from openkb_s4.models_v13 import V13Unit
    from openkb_s4.services.content_store import ContentStore

    app, client, users, headers, imported = await setup_v13(api)
    async with app.state.sessions() as db:
        unit = await db.scalar(select(V13Unit).where(V13Unit.import_id == imported))
        assert unit is not None
        identity = unit.id
        candidate = ContentStore(app.state.settings.data_dir / "controlled").read_json(unit.source_ref)
    candidate["gold"]["answer_points"][0] = "五个工作日内办理"
    proposed = await client.post(P + "/revisions", headers=headers,
        json={"unit_index_id": identity, "verifier_id": users["verifier"],
              "candidate": candidate, "reason": "修订合成表述"})
    if proposed.status_code in {403, 409, 422}:
        return
    assert proposed.status_code == 201, proposed.text
    headers = await login(client, "verifier")
    result = await client.post(P + f"/revisions/{proposed.json()['id']}/verify", headers=headers,
        json={"outcome": "PASS", "reason": "独立确认合成材料", "evidence": {"report": "synthetic-only"}})
    assert result.status_code in {403, 409, 422}, result.text


@pytest.mark.asyncio
async def test_pending_revision_is_reported_as_content_blocker(api: Any) -> None:
    from openkb_s4.models_v13 import V13Unit
    from openkb_s4.services.content_store import ContentStore

    app, client, users, headers, imported = await setup_v13(api)
    created = await client.post(P + "/verification-batches", headers=headers,
        json={"import_id": imported, "dataset": "QA-D1", "assignee_ids": [users["v"]]})
    assert created.status_code == 201, created.text
    headers = await login(client, "v")
    task = (await client.get(P + "/me/tasks")).json()["items"][0]
    assert (await submit(client, headers, task, {"answer": "独立答案", "reason": "原文"})).status_code == 200
    detail = (await client.get(P + f"/assignments/{task['id']}")).json()
    assert (await submit(client, headers, detail, review(detail, wrong=True))).status_code == 200
    headers = await login(client, "lead")
    async with app.state.sessions() as db:
        unit = await db.get(V13Unit, detail["unit_index_id"])
        assert unit is not None
        candidate = deepcopy(ContentStore(app.state.settings.data_dir / "controlled").read_json(unit.source_ref))
    candidate["gold"]["answer_points"][1] = "必须通过指定表单办理"
    proposed = await client.post(P + "/revisions", headers=headers,
        json={"unit_index_id": detail["unit_index_id"], "verifier_id": users["verifier"],
              "candidate": candidate, "reason": "修订合成渠道表述"})
    assert proposed.status_code == 201, proposed.text
    report = (await client.get(P + f"/imports/{imported}/report")).json()
    assert any("REVISION" in value and ("PENDING" in value or "UNRESOLVED" in value)
               for value in report["content_blockers"])


@pytest.mark.asyncio
async def test_unregistered_profile_and_changed_frozen_schema_are_rejected(api: Any) -> None:
    from openkb_s4.models_v13 import V13Batch

    app, client, users, headers, imported = await setup_v13(api)
    body = {"import_id": imported, "dataset": "QA-D1", "assignee_ids": [users["v"]]}
    invalid = await client.post(P + "/verification-batches", headers=headers,
                               json={**body, "profile_version": "pretend-approved"})
    assert invalid.status_code == 422
    created = await client.post(P + "/verification-batches", headers=headers, json=body)
    assert created.status_code == 201, created.text
    async with app.state.sessions() as db, db.begin():
        batch = await db.get(V13Batch, created.json()["id"])
        assert batch is not None
        batch.frozen_hash = "0" * 64
    headers = await login(client, "v")
    task = (await client.get(P + "/me/tasks")).json()["items"][0]
    result = await submit(client, headers, task, {"answer": "独立答案", "reason": "原文"})
    assert result.status_code == 409
    assert result.json()["error_code"] == "FROZEN_PROFILE_CONFLICT"


@pytest.mark.asyncio
async def test_replacement_is_whole_observation_seat_and_late_history_is_invalid(api: Any) -> None:
    from openkb_s4.models_v13 import V13LateSubmission

    app, client, users, headers, imported = await setup_v13(api)
    result = await client.post(P + "/observation-batches", headers=headers,
        json={"import_id": imported, "dataset": "QA-D1", "annotator_a": users["a"], "annotator_b": users["b"]})
    assert result.status_code == 201, result.text
    batch_id = result.json()["id"]
    headers = await login(client, "a")
    tasks = (await client.get(P + "/me/tasks")).json()["items"]
    assert (await submit(client, headers, tasks[0], {"answer": "本人盲答", "reason": "原文"})).status_code == 200
    headers = await login(client, "lead")
    replacement = await client.post(P + f"/assignments/{tasks[1]['id']}/replace", headers=headers,
        json={"user_id": users["other"], "reason": "原观测员离场"})
    assert replacement.status_code == 201, replacement.text
    assert replacement.json()["scope"] == "SEAT" and len(replacement.json()["assignment_ids"]) == 8
    headers = await login(client, "a")
    late = await submit(client, headers, tasks[1], {"answer": "迟到盲答", "reason": "保留原始历史"})
    assert late.status_code == 409 and late.json()["history_id"]
    again = await submit(client, headers, tasks[1], {"answer": "迟到盲答", "reason": "保留原始历史"})
    assert again.status_code == 409 and again.json()["history_id"] == late.json()["history_id"]
    async with app.state.sessions() as db:
        history = await db.get(V13LateSubmission, late.json()["history_id"])
        assert history is not None
    await login(client, "lead")
    batch = (await client.get(P + "/batches/" + batch_id)).json()
    assert batch["blind_submitted"] == 0


@pytest.mark.asyncio
async def test_material_issue_pauses_own_task_and_needs_independent_resolution(api: Any) -> None:
    _, client, users, headers, imported = await setup_v13(api)
    assert (await client.post(P + "/verification-batches", headers=headers,
        json={"import_id": imported, "dataset": "QA-D1", "assignee_ids": [users["v"]]})).status_code == 201
    headers = await login(client, "v")
    task = (await client.get(P + "/me/tasks")).json()["items"][0]
    issue = await client.post(P + "/issues", headers=headers,
        json={"unit_index_id": task["unit_index_id"], "reason": "原文材料范围需确认"})
    assert issue.status_code == 201, issue.text
    blocked = await submit(client, headers, task, {"answer": "独立答案", "reason": "原文"})
    assert blocked.status_code == 409 and blocked.json()["error_code"] == "MATERIAL_BLOCKED"
    own = await client.get(P + "/issues")
    assert own.status_code == 200 and len(own.json()["items"]) == 1
    headers = await login(client, "lead")
    resolved = await client.post(P + f"/issues/{issue.json()['id']}/resolve", headers=headers,
        json={"reason": "确认同版本原文范围完整", "evidence": {"scope_checked": True}})
    assert resolved.status_code == 200, resolved.text
    headers = await login(client, "v")
    assert (await submit(client, headers, task, {"answer": "独立答案", "reason": "原文"})).status_code == 200


@pytest.mark.asyncio
async def test_review_departure_starts_independent_new_round_preserving_scope(api: Any) -> None:
    from helpers import seed_user

    _, client, users, headers, imported = await setup_v13(api)
    app, _ = api
    users["new_b"] = await seed_user(app, "new_b", ["annotator"])
    observed = await client.post(P + "/observation-batches", headers=headers,
        json={"import_id": imported, "dataset": "QA-D1", "annotator_a": users["a"], "annotator_b": users["b"]})
    assert observed.status_code == 201
    for name in ("a", "b"):
        headers = await login(client, name)
        for task in (await client.get(P + "/me/tasks")).json()["items"]:
            assert (await submit(client, headers, task, {"answer": "本人独立判断", "reason": "原文"})).status_code == 200
    headers = await login(client, "lead")
    batch_id = observed.json()["id"]
    assert (await client.post(P + f"/observation-batches/{batch_id}/release-review", headers=headers)).status_code == 200
    headers = await login(client, "a")
    task = (await client.get(P + "/me/tasks")).json()["items"][0]
    assert (await client.get(P + f"/assignments/{task['id']}")).status_code == 200
    headers = await login(client, "lead")
    changed = await client.post(P + f"/batches/{batch_id}/new-round", headers=headers,
        json={"reason": "复核阶段人员离场，完整新轮", "annotator_a": users["other"], "annotator_b": users["new_b"]})
    assert changed.status_code == 201, changed.text
    assert changed.json()["selected_ids"] == observed.json()["selected_ids"]
    assert changed.json()["sample_ledger"]["purpose"] == "REPLACEMENT"
    assert (await client.get(P + "/batches/" + batch_id)).json()["state"] == "SUPERSEDED"
    await login(client, "other")
    tasks = (await client.get(P + "/me/tasks")).json()["items"]
    assert len(tasks) == 8 and all(task["phase"] == "BLIND" for task in tasks)


@pytest.mark.asyncio
async def test_matching_observation_findings_cannot_disappear_behind_high_kappa(api: Any) -> None:
    _, client, users, headers, imported = await setup_v13(api)
    observed = await client.post(P + "/observation-batches", headers=headers,
        json={"import_id": imported, "dataset": "QA-D1", "annotator_a": users["a"], "annotator_b": users["b"]})
    assert observed.status_code == 201
    for name in ("a", "b"):
        headers = await login(client, name)
        for task in (await client.get(P + "/me/tasks")).json()["items"]:
            assert (await submit(client, headers, task, {"answer": "独立判断", "reason": "原文"})).status_code == 200
    headers = await login(client, "lead")
    batch_id = observed.json()["id"]
    assert (await client.post(P + f"/observation-batches/{batch_id}/release-review", headers=headers)).status_code == 200
    first = None
    for name in ("a", "b"):
        headers = await login(client, name)
        for task in (await client.get(P + "/me/tasks")).json()["items"]:
            detail = (await client.get(P + f"/assignments/{task['id']}")).json()
            first = first or detail
            assert (await submit(client, headers, detail, review(detail, wrong=True))).status_code == 200
    headers = await login(client, "lead")
    quality = await client.post(P + f"/observation-batches/{batch_id}/observe", headers=headers)
    assert quality.status_code == 200 and quality.json()["kappa"] == 1
    report = (await client.get(P + f"/imports/{imported}/report")).json()
    assert "OBSERVATION_CONTENT_FINDINGS:8" in report["content_blockers"]
    assert first is not None
    resolution = await client.post(P + "/quality-actions", headers=headers, json={
        "batch_id": batch_id, "kind": "DISAGREEMENT_REVIEW", "reason": "独立核对原文，保留原草案渠道要点",
        "evidence": {"unit_index_id": first["unit_index_id"], "content_revision": first["content_revision"],
                     "resolution": "KEEP_SOURCE", "source_check": "指定表单确有原文支持"}})
    assert resolution.status_code == 201, resolution.text
    report = (await client.get(P + f"/imports/{imported}/report")).json()
    assert "OBSERVATION_CONTENT_FINDINGS:7" in report["content_blockers"]
    assert report["verification_completed"] == 0
    from helpers import seed_user
    app, _ = api
    expansion_b = await seed_user(app, "expansion_b", ["annotator"])
    expansion = await client.post(P + "/observation-batches", headers=headers, json={
        "import_id": imported, "dataset": "QA-D1", "parent_id": batch_id,
        "expanded_count": 9, "annotator_a": users["other"], "annotator_b": expansion_b})
    assert expansion.status_code == 201, expansion.text
    report = (await client.get(P + f"/imports/{imported}/report")).json()
    assert "EXPANSION_INCOMPLETE:" + expansion.json()["id"] in report["content_blockers"]
    assert report["n"] == 8 and report["expanded_observation_count"] == 9
    assert report["observation_scope_count"] == 9


@pytest.mark.asyncio
async def test_low_kappa_returns_entire_source_and_ack_cannot_reopen(api: Any) -> None:
    _, client, users, headers, imported = await setup_v13(api)
    observed = await client.post(P + "/observation-batches", headers=headers,
        json={"import_id": imported, "dataset": "QA-D1", "annotator_a": users["a"], "annotator_b": users["b"]})
    assert observed.status_code == 201
    for name in ("a", "b"):
        headers = await login(client, name)
        for task in (await client.get(P + "/me/tasks")).json()["items"]:
            assert (await submit(client, headers, task, {"answer": "本人独立判断", "reason": "原文"})).status_code == 200
    headers = await login(client, "lead")
    batch_id = observed.json()["id"]
    assert (await client.post(P + f"/observation-batches/{batch_id}/release-review", headers=headers)).status_code == 200
    for name in ("a", "b"):
        headers = await login(client, name)
        for task in (await client.get(P + "/me/tasks")).json()["items"]:
            detail = (await client.get(P + f"/assignments/{task['id']}")).json()
            assert (await submit(client, headers, detail, review(detail, wrong=name == "b"))).status_code == 200
    headers = await login(client, "lead")
    quality = await client.post(P + f"/observation-batches/{batch_id}/observe", headers=headers)
    assert quality.status_code == 200, quality.text
    assert quality.json()["kappa"] == 0 and quality.json()["action"] == "RETURN_TO_S2"
    ack = await client.post(P + "/quality-actions", headers=headers, json={"batch_id": batch_id,
        "kind": "S2_ACK", "reason": "仅登记真实接收，不恢复失败原批", "evidence": {"receipt_ref": "synthetic-only"}})
    assert ack.status_code == 201
    report = (await client.get(P + f"/imports/{imported}/report")).json()
    assert report["readiness"] == "RETURNED_TO_S2"
    assert (await client.post(P + "/handoffs", headers=headers, json={"import_id": imported})).status_code == 409
    assert (await client.post(P + f"/batches/{batch_id}/new-round", headers=headers,
        json={"reason": "试图只换人洗掉低κ", "annotator_a": users["other"], "annotator_b": users["v"]})).status_code == 409


@pytest.mark.asyncio
async def test_new_primary_round_appends_same_revision_without_counting_old_seal(api: Any) -> None:
    from openkb_s4.models_v13 import V13Verification

    app, client, users, headers, imported = await setup_v13(api, 2)
    main = await client.post(P + "/verification-batches", headers=headers,
        json={"import_id": imported, "dataset": "QA-D1", "assignee_ids": [users["v"]]})
    headers = await login(client, "v")
    first = (await client.get(P + "/me/tasks")).json()["items"][0]
    assert (await submit(client, headers, first, {"answer": "独立判断", "reason": "原文"})).status_code == 200
    detail = (await client.get(P + f"/assignments/{first['id']}")).json()
    assert (await submit(client, headers, detail, review(detail))).status_code == 200
    async with app.state.sessions() as db:
        historical = await db.scalar(select(V13Verification).where(V13Verification.assignment_id == first["id"]))
        assert historical is not None
        original_id, original_ref = historical.id, historical.record_ref
    headers = await login(client, "lead")
    fresh = await client.post(P + f"/batches/{main.json()['id']}/new-round", headers=headers,
        json={"reason": "部分完成后人员离场，完整新轮", "assignee_ids": [users["other"]]})
    assert fresh.status_code == 201, fresh.text
    report = (await client.get(P + f"/imports/{imported}/report")).json()
    assert report["verification_completed"] == 0
    headers = await login(client, "other")
    tasks = (await client.get(P + "/me/tasks")).json()["items"]
    assert len(tasks) == 2
    for task in tasks:
        assert (await submit(client, headers, task, {"answer": "新人员独立判断", "reason": "原文"})).status_code == 200
    for task in tasks:
        detail = (await client.get(P + f"/assignments/{task['id']}")).json()
        result = await submit(client, headers, detail, review(detail))
        assert result.status_code == 200, result.text
    await login(client, "lead")
    report = (await client.get(P + f"/imports/{imported}/report")).json()
    assert report["verification_completed"] == 2
    async with app.state.sessions() as db:
        historical = await db.get(V13Verification, original_id)
        assert historical is not None and historical.record_ref == original_ref


@pytest.mark.asyncio
async def test_new_primary_round_binds_current_final_candidate_without_inheriting_old_signature(api: Any) -> None:
    _, client, users, headers, imported = await setup_v13(api, 2)
    main = await client.post(P + "/verification-batches", headers=headers,
        json={"import_id": imported, "dataset": "QA-D1", "assignee_ids": [users["v"]]})
    headers = await login(client, "v")
    first = (await client.get(P + "/me/tasks")).json()["items"][0]
    assert (await submit(client, headers, first, {"answer": "独立判断", "reason": "原文"})).status_code == 200
    detail = (await client.get(P + f"/assignments/{first['id']}")).json()
    assert (await submit(client, headers, detail, review(detail, wrong=True))).status_code == 200
    headers = await login(client, "lead")
    candidate = (await client.get(P + f"/units/{detail['unit_index_id']}")).json()["candidate"]
    candidate["gold"]["answer_points"][1] = "通过指定表单办理"
    proposal = await client.post(P + "/revisions", headers=headers, json={
        "unit_index_id": detail["unit_index_id"], "verifier_id": users["verifier"],
        "candidate": candidate, "reason": "修订渠道表述"})
    assert proposal.status_code == 201, proposal.text
    headers = await login(client, "verifier")
    result = await client.post(P + f"/revisions/{proposal.json()['id']}/verify", headers=headers,
        json={"outcome": "PASS", "reason": "独立核对最终修订", "evidence": {"report": "synthetic-only"}})
    assert result.status_code == 200, result.text
    final_revision = result.json()["final_revision"]
    headers = await login(client, "lead")
    assert (await client.get(P + f"/imports/{imported}/report")).json()["verification_completed"] == 1
    fresh = await client.post(P + f"/batches/{main.json()['id']}/new-round", headers=headers,
        json={"reason": "部分完成后独立新轮", "assignee_ids": [users["other"]]})
    assert fresh.status_code == 201, fresh.text
    assert (await client.get(P + f"/imports/{imported}/report")).json()["verification_completed"] == 0
    headers = await login(client, "other")
    target = next(task for task in (await client.get(P + "/me/tasks")).json()["items"]
                  if task["unit_id"] == detail["unit_id"])
    assert target["content_revision"] == final_revision
    assert (await submit(client, headers, target, {"answer": "新人员独立判断", "reason": "原文"})).status_code == 200
    updated = (await client.get(P + f"/assignments/{target['id']}")).json()
    assert updated["gold"]["answer_points"][1] == "通过指定表单办理"
    assert (await submit(client, headers, updated, review(updated))).status_code == 200
    headers = await login(client, "lead")
    assert (await client.get(P + f"/imports/{imported}/report")).json()["verification_completed"] == 1
    unchanged = await client.post(P + "/revisions", headers=headers, json={
        "unit_index_id": detail["unit_index_id"], "verifier_id": users["verifier"],
        "candidate": candidate, "reason": "相同候选不可重复算签名"})
    assert unchanged.status_code == 422 and unchanged.json()["error_code"] == "REVISION_UNCHANGED"
