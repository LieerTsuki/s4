from copy import deepcopy

import pytest
from helpers import login, seed_user
from sqlalchemy import select
from test_workflow import setup_batch


@pytest.mark.asyncio
async def test_profiles_have_frozen_approved_baseline(api):
    app, client = api
    await seed_user(app, "lead", ["lead"])
    await login(client, "lead")
    response = await client.get("/api/s4/v1/profile-revisions")
    assert response.status_code == 200, response.text
    assert response.json()["total"] >= 12
    row = response.json()["items"][0]
    assert row["state"] == "APPROVED"
    assert len(row["canonical_hash"]) == 64


async def test_profile_approval_rejects_self_and_freezes_snapshot(api):
    app, c = api
    await seed_user(app, "lead", ["lead"])
    await seed_user(app, "other", ["lead"])
    h = await login(c, "lead")
    baseline = (await c.get("/api/s4/v1/profile-revisions")).json()["items"][0]
    snapshot = deepcopy(baseline["snapshot"])
    snapshot["version"] = "custom-v2"
    body = {
        "dataset": baseline["dataset"],
        "version": "custom-v2",
        "manual_version": snapshot["manual_version"],
        "snapshot": snapshot,
        "reason": "test-only clarification",
    }
    response = await c.post("/api/s4/v1/profile-revisions", headers=h, json=body)
    assert response.status_code == 201, response.text
    p = response.json()
    pid = p["id"]
    p = (
        await c.post(
            f"/api/s4/v1/profile-revisions/{pid}/submit",
            headers=h,
            json={"version": p["revision"], "reason": "review complete"},
        )
    ).json()
    denied = await c.post(
        f"/api/s4/v1/profile-revisions/{pid}/approve",
        headers=h,
        json={"version": p["revision"], "reason": "self approval"},
    )
    assert denied.status_code == 403, denied.text
    h = await login(c, "other")
    approved = await c.post(
        f"/api/s4/v1/profile-revisions/{pid}/approve",
        headers=h,
        json={
            "version": p["revision"],
            "reason": "independent review",
            "evidence": {"ref": "test-only evidence"},
        },
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["state"] == "APPROVED"
    changed = await c.patch(
        f"/api/s4/v1/profile-revisions/{pid}",
        headers=h,
        json={**body, "expected_revision": approved.json()["revision"]},
    )
    assert changed.status_code == 409


async def test_material_issue_pause_independent_resolve_and_resume(api):
    app, c = api
    _, batch, _ = await setup_batch(app, c)
    h = await login(c, "a")
    tasks = (await c.get("/api/s4/v1/me/tasks")).json()["items"]
    task = tasks[0]
    response = await c.post(
        "/api/s4/v1/work-issues",
        headers=h,
        json={
            "assignment_id": task["id"],
            "issue_type": "MISSING_SOURCE",
            "reason": "synthetic material has missing attachment",
            "locators": [],
        },
    )
    assert response.status_code == 201, response.text
    issue = response.json()
    body = {
        "phase": "BLIND",
        "content_revision": task["content_revision"],
        "profile_version": task["profile_version"],
        "payload": {"answer": "answer", "reason": "reason"},
    }
    assert (
        await c.post(
            f"/api/s4/v1/assignments/{task['id']}/submit",
            headers={**h, "Idempotency-Key": "blocked"},
            json=body,
        )
    ).status_code == 409
    h = await login(c, "b")
    assert (await c.get("/api/s4/v1/work-issues")).json()["total"] == 0
    h = await login(c, "lead")
    resolved = await c.post(
        f"/api/s4/v1/work-issues/{issue['id']}/resolve",
        headers=h,
        json={
            "version": 1,
            "reason": "independently confirmed material unchanged",
            "disposition": "UNCHANGED",
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert (await c.get(f"/api/s4/v1/annotation-batches/{batch['id']}")).json()[
        "state"
    ] == "BLIND_OPEN"


async def test_whole_seat_replacement_and_late_submission_preserves_history(api):
    from openkb_s4.models import Assignment, LateSubmission

    app, c = api
    _, batch, _ = await setup_batch(app, c)
    new = await seed_user(app, "new", ["annotator"])
    h = await login(c, "a")
    old = (await c.get("/api/s4/v1/me/tasks")).json()["items"][0]
    h = await login(c, "lead")
    replacement = await c.post(
        f"/api/s4/v1/annotation-batches/{batch['id']}/replace-seat",
        headers=h,
        json={
            "seat": "A",
            "new_annotator_id": new,
            "reason": "synthetic availability change",
            "version": 1,
        },
    )
    assert replacement.status_code == 200, replacement.text
    assert replacement.json()["sample_count"] == 8
    h = await login(c, "a")
    late = await c.post(
        f"/api/s4/v1/assignments/{old['id']}/submit",
        headers={**h, "Idempotency-Key": "late"},
        json={
            "phase": "BLIND",
            "content_revision": old["content_revision"],
            "profile_version": old["profile_version"],
            "payload": {"answer": "late answer", "reason": "test"},
        },
    )
    assert late.status_code == 409, late.text
    assert late.json()["error_code"] == "INVALID_LATE"
    assert late.json()["history_id"]
    async with app.state.sessions() as db:
        assert (
            len(
                (
                    await db.scalars(
                        select(Assignment).where(
                            Assignment.batch_id == batch["id"], Assignment.active.is_(True)
                        )
                    )
                ).all()
            )
            == 16
        )
        assert await db.scalar(select(LateSubmission)) is not None


async def test_blind_queries_only_material_revision(api):
    from sqlalchemy import event

    app, c = api
    _, _, _ = await setup_batch(app, c)
    await login(c, "a")
    task = (await c.get("/api/s4/v1/me/tasks")).json()["items"][0]
    queries = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement.lower())

    event.listen(app.state.engine.sync_engine, "before_cursor_execute", capture)
    try:
        response = await c.get(f"/api/s4/v1/assignments/{task['id']}")
    finally:
        event.remove(app.state.engine.sync_engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    assert not any("source_imports.payload" in sql or "gold_revisions" in sql for sql in queries), (
        queries
    )
    assert response.json()["review_version"] == "openkb.s4-review.v2"


async def test_validation_candidate_requires_independent_evidence_and_final_gate(api):
    from helpers import demo_payload, finish_reviews

    from openkb_s4.domain.contracts import canonical_sha256
    from openkb_s4.services.revisions import final_candidate

    app, c = api
    _, batch, _ = await setup_batch(app, c)
    verifier_id = await seed_user(app, "verify", ["verifier"])
    h, agreement = await finish_reviews(app, c, batch)
    units = {u["unit_id"]: u for u in demo_payload()["units"]}
    decisions = [
        {
            "unit_id": uid,
            "final_gold": deepcopy(units[uid]["gold"]),
            "reason": "synthetic final source inspection",
        }
        for uid in batch["selected_ids"]
    ]
    decisions[0]["final_gold"]["answer_points"][0] = "synthetic corrected point"
    response = await c.post(
        f"/api/s4/v1/annotation-batches/{batch['id']}/finalize",
        headers=h,
        json={"decisions": decisions},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error_code"] == "VALIDATION_REQUIRED"
    proposal = await c.post(
        "/api/s4/v1/validation-candidates",
        headers=h,
        json={"batch_id": batch["id"], "verifier_id": verifier_id, **decisions[0]},
    )
    assert proposal.status_code == 201, proposal.text
    h = await login(c, "verify")
    response = await c.get(
        "/api/s4/v1/validation-candidates",
        params={"batch_id": batch["id"], "unit_id": decisions[0]["unit_id"]},
    )
    assert response.status_code == 200, response.text
    candidate = response.json()
    assert candidate["contexts"]
    expected = canonical_sha256(
        final_candidate(units[decisions[0]["unit_id"]], decisions[0]["final_gold"])
    )
    assert candidate["content_hash"] == expected
    evidence = {
        "kind": "synthetic",
        "revision": "synthetic-revalidation-v1",
        "content_hash": expected,
        "profile_hash": batch["profile_hash"],
        "point_results": [
            {"point_key": key, "status": "PASS", "reason": "synthetic independent source check"}
            for key in ["P001", "P002"]
        ],
        "locators": [
            {"doc_id": decisions[0]["final_gold"]["gold_doc_ids"][0], "start": 0, "end": 5}
        ],
    }
    body = {
        "batch_id": batch["id"],
        "unit_id": decisions[0]["unit_id"],
        "final_gold": decisions[0]["final_gold"],
        "content_hash": expected,
        "profile_hash": batch["profile_hash"],
        "evidence": evidence,
        "reason": "synthetic independent validation",
    }
    bad = deepcopy(body)
    bad["evidence"]["passed"] = True
    assert (await c.post("/api/s4/v1/validation-revisions", headers=h, json=bad)).status_code == 422
    response = await c.post("/api/s4/v1/validation-revisions", headers=h, json=body)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "PASS"
    h = await login(c, "lead")
    response = await c.post(
        f"/api/s4/v1/annotation-batches/{batch['id']}/finalize",
        headers=h,
        json={"decisions": decisions},
    )
    assert response.status_code == 200, response.text


async def test_calibration_qualification_and_full_round_change_are_accountable(api):
    from helpers import calibration

    app, c = api
    h, batch, people = await setup_batch(app, c)
    fresh_a = await seed_user(app, "fresh_a", ["annotator"])
    fresh_b = await seed_user(app, "fresh_b", ["annotator"])
    denied = await c.post(
        "/api/s4/v1/rounds",
        headers=h,
        json={
            "batch_id": batch["id"],
            "annotator_a": fresh_a,
            "annotator_b": fresh_b,
            "seed": 42,
            "reason": "test new round",
        },
    )
    assert denied.status_code == 409 and denied.json()["error_code"] == "CALIBRATION_REQUIRED"
    cal = await calibration(c, h, batch)
    assert (await c.get("/api/s4/v1/calibrations")).json()["total"] == 1
    response = await c.post(
        "/api/s4/v1/qualifications",
        headers=h,
        json={
            "user_id": fresh_a,
            "dataset": "QA-D1",
            "available": False,
            "valid_until": "2030-01-01T00:00:00Z",
            "evidence": {"ref": "synthetic test availability approval"},
            "reason": "test unavailable",
        },
    )
    assert response.status_code == 201, response.text
    body = {
        "batch_id": batch["id"],
        "calibration_id": cal,
        "manual_version": batch["manual_version"],
        "annotator_a": fresh_a,
        "annotator_b": fresh_b,
        "seed": 42,
        "reason": "test full batch round",
    }
    denied = await c.post("/api/s4/v1/rounds", headers=h, json=body)
    assert denied.status_code == 409 and denied.json()["error_code"] == "ANNOTATOR_UNAVAILABLE"
    response = await c.post(
        "/api/s4/v1/qualifications",
        headers=h,
        json={
            "user_id": fresh_a,
            "dataset": "QA-D1",
            "available": True,
            "valid_until": "2030-01-01T00:00:00Z",
            "evidence": {"ref": "synthetic test availability approved"},
            "reason": "test available",
        },
    )
    assert response.status_code == 201, response.text
    response = await c.post("/api/s4/v1/rounds", headers=h, json=body)
    assert response.status_code == 201, response.text
    assert response.json()["calibration_id"] == cal
    assert response.json()["parent_id"] == batch["id"]
    h = await login(c, "fresh_a")
    assert (await c.get("/api/s4/v1/qualifications")).json()["total"] == 2
    assert (await c.get("/api/s4/v1/calibrations")).status_code == 403


async def test_profile_publication_invalidates_affected_batches_and_old_client(api):
    app, c = api
    h, batch, _ = await setup_batch(app, c)
    await seed_user(app, "approver", ["lead"])
    baseline = (await c.get(f"/api/s4/v1/profile-revisions/{batch['profile_revision_id']}")).json()
    snapshot = deepcopy(baseline["snapshot"])
    snapshot["version"] = "published-test-v2"
    snapshot["instructions"] = "synthetic revised instructions"
    response = await c.post(
        "/api/s4/v1/profile-revisions",
        headers=h,
        json={
            "dataset": "QA-D1",
            "version": snapshot["version"],
            "manual_version": snapshot["manual_version"],
            "snapshot": snapshot,
            "reason": "test rule clarification",
        },
    )
    assert response.status_code == 201, response.text
    profile = response.json()
    response = await c.post(
        f"/api/s4/v1/profile-revisions/{profile['id']}/submit",
        headers=h,
        json={"version": 1, "reason": "test submit"},
    )
    assert response.status_code == 200, response.text
    h = await login(c, "approver")
    response = await c.post(
        f"/api/s4/v1/profile-revisions/{profile['id']}/approve",
        headers=h,
        json={
            "version": 2,
            "reason": "test independent approval",
            "evidence": {"ref": "synthetic test evidence"},
        },
    )
    assert response.status_code == 200, response.text
    detail = (await c.get(f"/api/s4/v1/annotation-batches/{batch['id']}")).json()
    assert detail["state"] == "PAUSED"
    assert "PROFILE_REVISION_CHANGED" in detail["blocked_reasons"]
    assert detail["profile_hash"] == batch["profile_hash"]
    h = await login(c, "a")
    task = (await c.get("/api/s4/v1/me/tasks")).json()["items"][0]
    response = await c.post(
        f"/api/s4/v1/assignments/{task['id']}/submit",
        headers={**h, "Idempotency-Key": "stale-client"},
        json={
            "phase": "BLIND",
            "content_revision": task["content_revision"],
            "profile_version": task["profile_version"],
            "payload": {"answer": "test", "reason": "test"},
        },
    )
    assert response.status_code == 409


async def test_pause_resume_versions_and_issue_new_revision_keep_old_scope_closed(api):
    app, c = api
    h, batch, _ = await setup_batch(app, c)
    url = f"/api/s4/v1/annotation-batches/{batch['id']}"
    response = await c.post(
        url + "/pause", headers=h, json={"version": 1, "reason": "synthetic operational pause"}
    )
    assert response.status_code == 200, response.text
    assert (
        await c.post(url + "/resume", headers=h, json={"version": 1, "reason": "stale"})
    ).status_code == 409
    assert (
        await c.post(
            url + "/resume",
            headers=h,
            json={"version": 2, "reason": "independently checked unchanged"},
        )
    ).status_code == 200
    h = await login(c, "a")
    task = (await c.get("/api/s4/v1/me/tasks")).json()["items"][0]
    issue = (
        await c.post(
            "/api/s4/v1/work-issues",
            headers=h,
            json={
                "assignment_id": task["id"],
                "issue_type": "EARLY_EXPOSURE",
                "reason": "synthetic accidental prior draft exposure",
            },
        )
    ).json()
    h = await login(c, "lead")
    response = await c.post(
        f"/api/s4/v1/work-issues/{issue['id']}/resolve",
        headers=h,
        json={"version": 1, "reason": "unchanged content", "disposition": "UNCHANGED"},
    )
    assert (
        response.status_code == 409
        and response.json()["error_code"] == "EXPOSURE_REQUIRES_NEW_ROUND"
    )
    assert (
        await c.post(url + "/resume", headers=h, json={"version": 4, "reason": "still open"})
    ).status_code == 409


async def test_replacement_optimistic_version_and_active_unique_are_database_enforced(api):
    from sqlalchemy.exc import IntegrityError

    from openkb_s4.models import Assignment

    app, c = api
    h, batch, _ = await setup_batch(app, c)
    fresh = await seed_user(app, "fresh", ["annotator"])
    body = {"seat": "A", "new_annotator_id": fresh, "version": 1, "reason": "test replacement"}
    url = f"/api/s4/v1/annotation-batches/{batch['id']}/replace-seat"
    assert (await c.post(url, headers=h, json={**body, "version": 2})).status_code == 409
    async with app.state.sessions() as db:
        old = await db.scalar(
            select(Assignment).where(Assignment.batch_id == batch["id"], Assignment.seat == "A")
        )
        db.add(
            Assignment(
                batch_id=old.batch_id,
                unit_id=old.unit_id,
                user_id=fresh,
                seat="A",
                content_revision=old.content_revision,
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()
    assert (await c.post(url, headers=h, json=body)).status_code == 200
    assert (await c.post(url, headers=h, json=body)).status_code == 409


async def test_new_immutable_revisions_and_approved_profiles_cannot_be_rewritten(api):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    app, c = api
    await setup_batch(app, c)
    for statement in [
        "UPDATE unit_revisions SET material='{}'::json",
        "DELETE FROM gold_revisions",
        "UPDATE profile_revisions SET snapshot='{}'::json WHERE state='APPROVED'",
        "DELETE FROM profile_revisions WHERE dataset='QA-D4'",
    ]:
        async with app.state.sessions() as db:
            with pytest.raises(DBAPIError):
                await db.execute(text(statement))
            await db.rollback()


async def test_verifier_cannot_self_validate_or_validate_an_unregistered_candidate(api):
    from helpers import demo_payload, finish_reviews

    from openkb_s4.models import User

    app, c = api
    _, batch, people = await setup_batch(app, c)
    h, _ = await finish_reviews(app, c, batch)
    async with app.state.sessions() as db, db.begin():
        person = await db.get(User, people["lead"])
        person.roles = ["lead", "verifier"]
    verifier_id = await seed_user(app, "other_verifier", ["verifier"])
    unit = next(u for u in demo_payload()["units"] if u["unit_id"] == batch["selected_ids"][0])
    gold = deepcopy(unit["gold"])
    gold["answer_points"][0] = "synthetic changed candidate"
    response = await c.post(
        "/api/s4/v1/validation-candidates",
        headers=h,
        json={
            "batch_id": batch["id"],
            "verifier_id": verifier_id,
            "unit_id": unit["unit_id"],
            "final_gold": gold,
            "reason": "test proposal",
        },
    )
    assert response.status_code == 201, response.text
    candidate = response.json()
    body = {
        "batch_id": batch["id"],
        "unit_id": unit["unit_id"],
        "final_gold": gold,
        "content_hash": candidate["content_hash"],
        "profile_hash": batch["profile_hash"],
        "evidence": {},
        "reason": "self validation test",
    }
    response = await c.post("/api/s4/v1/validation-revisions", headers=h, json=body)
    assert response.status_code == 403, response.text
    h = await login(c, "a")
    assert (
        await c.get(
            "/api/s4/v1/validation-candidates",
            params={"batch_id": batch["id"], "unit_id": unit["unit_id"]},
        )
    ).status_code == 403


async def test_review_open_replacement_is_rejected_and_legacy_sealing_is_blocked(api):
    from helpers import finish_reviews

    from openkb_s4.models import AnnotationBatch

    app, c = api
    _, batch, _ = await setup_batch(app, c)
    fresh = await seed_user(app, "fresh", ["annotator"])
    h, _ = await finish_reviews(app, c, batch)
    response = await c.post(
        f"/api/s4/v1/annotation-batches/{batch['id']}/replace-seat",
        headers=h,
        json={"seat": "A", "new_annotator_id": fresh, "reason": "test after review", "version": 1},
    )
    assert (
        response.status_code == 409 and response.json()["error_code"] == "SEAT_REPLACEMENT_CLOSED"
    )
    # Explicitly simulate a migrated old unfinished batch; no old submission is changed.
    async with app.state.sessions() as db, db.begin():
        old = await db.get(AnnotationBatch, batch["id"])
        old.review_version = "openkb.s4-review.v1"
        old.state = "BLIND_OPEN"
    h = await login(c, "a")
    task = (await c.get("/api/s4/v1/me/tasks")).json()["items"][0]
    response = await c.patch(
        f"/api/s4/v1/assignments/{task['id']}/draft",
        headers=h,
        json={"phase": "BLIND", "version": 0, "payload": {"answer": "new", "reason": "new"}},
    )
    assert (
        response.status_code == 409
        and response.json()["error_code"] == "LEGACY_ROUND_UPGRADE_REQUIRED"
    )


async def test_replaced_participant_with_lead_role_remains_restricted(api):
    from openkb_s4.models import User

    app, c = api
    h, batch, people = await setup_batch(app, c)
    fresh = await seed_user(app, "fresh", ["annotator"])
    assert (
        await c.post(
            f"/api/s4/v1/annotation-batches/{batch['id']}/replace-seat",
            headers=h,
            json={"seat": "A", "new_annotator_id": fresh, "reason": "test replace", "version": 1},
        )
    ).status_code == 200
    async with app.state.sessions() as db, db.begin():
        person = await db.get(User, people["a"])
        person.roles = ["annotator", "lead", "auditor"]
    h = await login(c, "a")
    assert (await c.get(f"/api/s4/v1/annotation-batches/{batch['id']}")).status_code == 403
    assert (await c.get("/api/s4/v1/annotation-batches")).json()["items"] == []
    assert (await c.get("/api/s4/v1/imports")).json()["items"] == []
    async with app.state.sessions() as db:
        from openkb_s4.security import ApiError
        from openkb_s4.services.common import prohibit_participant_import

        person = await db.get(User, people["a"])
        with pytest.raises(ApiError):
            await prohibit_participant_import(db, person, batch["import_id"])


async def test_d7_review_resolves_frozen_source_case_ids_without_guessing_k(api):
    from helpers import demo_payload

    from openkb_s4.api.workflow import add_batch
    from openkb_s4.domain.contracts import canonical_sha256
    from openkb_s4.models import SourceImport
    from openkb_s4.schemas import BatchCreate

    app, c = api
    _, _, people = await setup_batch(app, c)
    payload = demo_payload()
    d7 = []
    for index in range(8):
        item = deepcopy(payload["units"][index])
        item["unit_id"] = f"QA-D7-{index:04d}"
        item["dataset"] = "QA-D7"
        item["source_case_ids"] = [payload["units"][index]["unit_id"], "QA-D2-missing"]
        item["evaluation_k"] = 1
        d7.append(item)
    payload["units"] += d7
    payload["batch_id"] = "D7-RESOLUTION-TEST"
    async with app.state.sessions() as db, db.begin():
        source = SourceImport(
            batch_id=payload["batch_id"],
            source_revision="r1",
            mode="demo",
            payload=payload,
            content_hash=canonical_sha256(payload),
            creator_id=people["lead"],
            blocked_reasons=["D7_K_RULE_REQUIRES_APPROVAL"],
        )
        db.add(source)
        await db.flush()
        batch = await add_batch(
            db,
            source,
            BatchCreate(
                import_id=source.id,
                dataset="QA-D7",
                annotator_a=people["a"],
                annotator_b=people["b"],
                seed=1,
            ),
        )
        batch.state = "REVIEW_OPEN"
        batch_id = batch.id
    await login(c, "a")
    tasks = (await c.get("/api/s4/v1/me/tasks")).json()["items"]
    task = next(t for t in tasks if t["batch_id"] == batch_id)
    detail = (await c.get(f"/api/s4/v1/assignments/{task['id']}")).json()
    assert detail["material"]["resolved_sources"][0]["status"] == "RESOLVED"
    assert detail["material"]["resolved_sources"][1]["status"] == "NOT_IN_FROZEN_IMPORT"
    assert detail["material"]["evidence_union"] == detail["gold"]["gold_doc_ids"]
    assert detail["material"]["source_composition"] == {"QA-D1": 1, "UNRESOLVED": 1}
    assert detail["material"]["k_rule_status"] == "UNCONFIRMED"


async def test_verifier_role_does_not_grant_another_verifiers_candidate(api):
    from helpers import demo_payload, finish_reviews

    app, c = api
    _, batch, _ = await setup_batch(app, c)
    assigned = await seed_user(app, "assigned", ["verifier"])
    await seed_user(app, "unassigned", ["verifier"])
    h, _ = await finish_reviews(app, c, batch)
    uid = batch["selected_ids"][0]
    gold = next(unit["gold"] for unit in demo_payload()["units"] if unit["unit_id"] == uid)
    response = await c.post(
        "/api/s4/v1/validation-candidates",
        headers=h,
        json={
            "batch_id": batch["id"],
            "unit_id": uid,
            "final_gold": gold,
            "verifier_id": assigned,
            "reason": "test controlled assignment",
        },
    )
    assert response.status_code == 201, response.text
    await login(c, "unassigned")
    response = await c.get(
        "/api/s4/v1/validation-candidates", params={"batch_id": batch["id"], "unit_id": uid}
    )
    assert response.status_code == 404, response.text


async def test_core_lists_paginate_using_authorized_total(api):
    from helpers import finish_reviews

    app, c = api
    h, batch, _ = await setup_batch(app, c)
    assert (await c.get("/api/s4/v1/users", params={"offset": 1, "limit": 1})).json()["total"] == 4
    assert (
        len((await c.get("/api/s4/v1/users", params={"offset": 1, "limit": 1})).json()["items"])
        == 1
    )
    page = (await c.get("/api/s4/v1/annotation-batches", params={"offset": 1, "limit": 1})).json()
    assert page["total"] == 1 and page["items"] == []
    await login(c, "a")
    page = (await c.get("/api/s4/v1/me/tasks", params={"offset": 2, "limit": 3})).json()
    assert page["total"] == 8 and len(page["items"]) == 3
    h, _ = await finish_reviews(app, c, batch)
    page = (await c.get("/api/s4/v1/agreements", params={"offset": 1, "limit": 1})).json()
    assert page["total"] == 1 and page["items"] == []


async def test_assignment_cached_before_replacement_is_refreshed_under_batch_lock(api):
    from openkb_s4.models import Assignment, User
    from openkb_s4.security import ApiError
    from openkb_s4.services.common import own_assignment

    app, c = api
    h, batch, people = await setup_batch(app, c)
    fresh = await seed_user(app, "fresh", ["annotator"])
    async with app.state.sessions() as cached_db:
        old = await cached_db.scalar(
            select(Assignment).where(Assignment.batch_id == batch["id"], Assignment.seat == "A")
        )
        actor = await cached_db.get(User, people["a"])
        assert old.active is True
        response = await c.post(
            f"/api/s4/v1/annotation-batches/{batch['id']}/replace-seat",
            headers=h,
            json={
                "seat": "A",
                "new_annotator_id": fresh,
                "version": 1,
                "reason": "test cached request race",
            },
        )
        assert response.status_code == 200, response.text
        with pytest.raises(ApiError) as error:
            await own_assignment(cached_db, actor, old.id)
        assert error.value.code == "ASSIGNMENT_REPLACED"


async def test_resolved_material_revision_creates_new_round_from_new_frozen_source(api):
    from helpers import calibration, demo_payload

    from openkb_s4.domain.contracts import canonical_sha256
    from openkb_s4.models import SourceImport

    app, c = api
    h, batch, people = await setup_batch(app, c)
    fresh_a = await seed_user(app, "fresh_a", ["annotator"])
    fresh_b = await seed_user(app, "fresh_b", ["annotator"])
    payload = demo_payload()
    payload["source_revision"] = "corrected-r2"
    payload["units"][0]["question"] = "synthetic materially corrected question"
    async with app.state.sessions() as db, db.begin():
        imported = SourceImport(
            batch_id=payload["batch_id"],
            source_revision=payload["source_revision"],
            mode="demo",
            payload=payload,
            content_hash=canonical_sha256(payload),
            creator_id=people["lead"],
            blocked_reasons=[],
        )
        db.add(imported)
        await db.flush()
        new_import_id = imported.id
    h = await login(c, "a")
    task = (await c.get("/api/s4/v1/me/tasks")).json()["items"][0]
    issue = (
        await c.post(
            "/api/s4/v1/work-issues",
            headers=h,
            json={
                "assignment_id": task["id"],
                "issue_type": "VERSION_CONFLICT",
                "reason": "synthetic stale material",
            },
        )
    ).json()
    h = await login(c, "lead")
    response = await c.post(
        f"/api/s4/v1/work-issues/{issue['id']}/resolve",
        headers=h,
        json={
            "version": 1,
            "disposition": "NEW_REVISION",
            "revision_ref": new_import_id,
            "reason": "synthetic independent corrected source review",
        },
    )
    assert response.status_code == 200, response.text
    cal = await calibration(c, h, batch)
    response = await c.post(
        "/api/s4/v1/rounds",
        headers=h,
        json={
            "batch_id": batch["id"],
            "calibration_id": cal,
            "annotator_a": fresh_a,
            "annotator_b": fresh_b,
            "seed": 42,
            "reason": "synthetic full new revision round",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["import_id"] == new_import_id
    assert response.json()["parent_id"] == batch["id"]


async def test_round_cannot_change_manual_without_matching_approved_profile(api):
    app, c = api
    h, batch, people = await setup_batch(app, c)
    fresh_a = await seed_user(app, "fresh_a", ["annotator"])
    fresh_b = await seed_user(app, "fresh_b", ["annotator"])
    response = await c.post(
        "/api/s4/v1/calibrations",
        headers=h,
        json={
            "batch_id": batch["id"],
            "meeting_at": "2026-10-28T00:00:00Z",
            "participant_ids": [people["a"], people["b"]],
            "case_refs": [batch["selected_ids"][0]],
            "decisions": "synthetic new manual discussion",
            "manual_version": "unapproved-manual-v9",
            "training_refs": ["synthetic-training"],
            "reason": "test unapproved manual",
        },
    )
    assert response.status_code == 201, response.text
    cal = response.json()["id"]
    response = await c.post(
        "/api/s4/v1/rounds",
        headers=h,
        json={
            "batch_id": batch["id"],
            "calibration_id": cal,
            "manual_version": "unapproved-manual-v9",
            "annotator_a": fresh_a,
            "annotator_b": fresh_b,
            "seed": 42,
            "reason": "test manual mismatch",
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["error_code"] == "MANUAL_VERSION_CONFLICT"


async def test_validation_list_read_disqualifies_first_blind_for_source_family(api):
    from helpers import calibration, demo_payload, finish_reviews

    app, c = api
    _, batch, _ = await setup_batch(app, c)
    verifier = await seed_user(app, "verifier", ["verifier"])
    reader = await seed_user(app, "reader", ["lead", "annotator"])
    fresh = await seed_user(app, "fresh", ["annotator"])
    h, _ = await finish_reviews(app, c, batch)
    uid = batch["selected_ids"][0]
    gold = next(unit["gold"] for unit in demo_payload()["units"] if unit["unit_id"] == uid)
    assert (
        await c.post(
            "/api/s4/v1/validation-candidates",
            headers=h,
            json={
                "batch_id": batch["id"],
                "unit_id": uid,
                "final_gold": gold,
                "verifier_id": verifier,
                "reason": "synthetic candidate",
            },
        )
    ).status_code == 201
    h = await login(c, "reader")
    assert (await c.get("/api/s4/v1/validation-revisions")).json()["total"] == 1
    cal = await calibration(c, h, batch)
    response = await c.post(
        "/api/s4/v1/rounds",
        headers=h,
        json={
            "batch_id": batch["id"],
            "calibration_id": cal,
            "annotator_a": reader,
            "annotator_b": fresh,
            "seed": 42,
            "reason": "test reader cannot blind",
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["error_code"] == "PREVIOUS_EXPOSURE"


async def test_arbitration_content_author_cannot_be_assigned_as_independent_verifier(api):
    from helpers import finish_reviews

    from openkb_s4.models import User

    app, c = api
    _, batch, people = await setup_batch(app, c)
    async with app.state.sessions() as db, db.begin():
        judge = await db.get(User, people["judge"])
        judge.roles = ["arbitrator", "verifier"]
    _, agreement = await finish_reviews(app, c, batch, flips=3)
    from helpers import demo_payload

    uid = agreement["disagreement_unit_ids"][0]
    gold = deepcopy(
        next(unit["gold"] for unit in demo_payload()["units"] if unit["unit_id"] == uid)
    )
    gold["answer_points"][0] = "synthetic arbitration correction"
    h = await login(c, "judge")
    decision = await c.post(
        "/api/s4/v1/arbitrations",
        headers=h,
        json={
            "batch_id": batch["id"],
            "unit_id": uid,
            "final_gold": gold,
            "reason": "synthetic arbitration correction",
        },
    )
    assert decision.status_code == 201, decision.text
    h = await login(c, "lead")
    assert (
        await c.post(
            f"/api/s4/v1/arbitrations/{decision.json()['id']}/confirm",
            headers=h,
            json={"reason": "synthetic independent confirmation"},
        )
    ).status_code == 200
    response = await c.post(
        "/api/s4/v1/validation-candidates",
        headers=h,
        json={
            "batch_id": batch["id"],
            "unit_id": uid,
            "final_gold": gold,
            "verifier_id": people["judge"],
            "reason": "test independence",
        },
    )
    assert response.status_code == 403, response.text
    assert response.json()["error_code"] == "INDEPENDENT_VERIFIER_REQUIRED"


async def test_calibration_case_participant_cannot_receive_first_blind_same_family(api):
    app, c = api
    h, batch, people = await setup_batch(app, c)
    attendee = await seed_user(app, "attendee", ["annotator"])
    fresh = await seed_user(app, "fresh", ["annotator"])
    response = await c.post(
        "/api/s4/v1/calibrations",
        headers=h,
        json={
            "batch_id": batch["id"],
            "meeting_at": "2026-10-28T00:00:00Z",
            "participant_ids": [attendee, people["a"]],
            "case_refs": [batch["selected_ids"][0]],
            "decisions": "synthetic discussion of disputed answer case",
            "manual_version": batch["manual_version"],
            "training_refs": ["synthetic-case-training"],
            "reason": "test case discussion exposure",
        },
    )
    assert response.status_code == 201, response.text
    cal = response.json()["id"]
    response = await c.post(
        "/api/s4/v1/rounds",
        headers=h,
        json={
            "batch_id": batch["id"],
            "calibration_id": cal,
            "annotator_a": attendee,
            "annotator_b": fresh,
            "seed": batch["seed"],
            "reason": "test exposed attendee cannot blind same case",
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["error_code"] == "PREVIOUS_EXPOSURE"


async def test_profile_patch_rejects_stale_draft_revision(api):
    app, c = api
    await seed_user(app, "lead", ["lead"])
    await seed_user(app, "other", ["lead"])
    h = await login(c, "lead")
    baseline = (await c.get("/api/s4/v1/profile-revisions")).json()["items"][0]
    snapshot = deepcopy(baseline["snapshot"])
    snapshot["version"] = "optimistic-test-v2"
    body = {
        "dataset": baseline["dataset"],
        "version": snapshot["version"],
        "manual_version": snapshot["manual_version"],
        "snapshot": snapshot,
        "reason": "synthetic shared draft",
    }
    response = await c.post("/api/s4/v1/profile-revisions", headers=h, json=body)
    assert response.status_code == 201, response.text
    draft = response.json()
    url = f"/api/s4/v1/profile-revisions/{draft['id']}"
    first = await c.patch(url, headers=h, json={**body, "expected_revision": 1})
    assert first.status_code == 200, first.text
    h = await login(c, "other")
    second = await c.patch(url, headers=h, json={**body, "expected_revision": 1})
    assert second.status_code == 409, second.text
    assert second.json()["error_code"] == "VERSION_CONFLICT"
