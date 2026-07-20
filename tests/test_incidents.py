import json
import threading
from pathlib import Path

import pytest

import lifeline.incidents as incident_module
from lifeline.approvals import ApprovalChainError
from lifeline.incidents import IncidentConflict, IncidentStore, IncidentStoreError, _digest
from lifeline.export import seal_digest
from lifeline.verification import verify_payload


REPO = Path(__file__).resolve().parent.parent


def _scenario() -> dict:
    return json.loads((REPO / "scenarios" / "flood_v1.json").read_text(encoding="utf-8"))


def _request(request_id: str) -> dict:
    return {
        "request_id": request_id,
        "people": 2,
        "urgency": 4,
        "medical_need": False,
        "pickup_zone": "north-bank",
        "destination_zone": "shelter-a",
        "source": "operator-99",
        "source_type": "verified_operator",
        "observed_at": "2026-07-17T10:00:00Z",
        "verification_state": "verified",
        "freshness": "high",
    }


def test_incident_store_validates_appends_and_seals_plans(tmp_path):
    store = IncidentStore(tmp_path / "incidents.sqlite3")
    created = store.create(_scenario())
    assert created.incident_id == "flood-v1-synthetic"
    assert created.revision == 1
    assert store.list("flood-v1") == [{
        "incident_id": "flood-v1-synthetic",
        "revision": 1,
        "scenario_sha256": created.scenario_sha256,
        "updated_at": created.updated_at,
    }]

    updated = store.add_report(created.incident_id, "request", _request("family-new"))
    assert updated.revision == 2
    assert any(item["request_id"] == "family-new" for item in updated.scenario["requests"])
    events = store.events(created.incident_id)
    assert [event["event_type"] for event in events] == ["incident_created", "report_added"]
    assert events[1]["prev_hash"] == events[0]["event_hash"]

    planned = store.plan(created.incident_id, "2026-07-17T11:00:00Z")
    assert planned["revision"] == 2
    assert planned["seal"]["sha256"]
    assert planned["plan"]["scenario_id"] == created.incident_id


def test_incident_store_rejects_duplicate_additions(tmp_path):
    store = IncidentStore(tmp_path / "incidents.sqlite3")
    created = store.create(_scenario())
    with pytest.raises(IncidentConflict):
        store.create(_scenario())
    with pytest.raises(IncidentConflict):
        store.add_report(created.incident_id, "request", _scenario()["requests"][0])


def test_incident_store_supersedes_without_erasing_the_prior_event(tmp_path):
    store = IncidentStore(tmp_path / "incidents.sqlite3")
    created = store.create(_scenario())
    correction = _scenario()["resources"][0] | {"available": False, "observed_at": "2026-07-17T10:30:00Z"}
    updated = store.supersede_report(created.incident_id, "resource", correction)

    current = next(item for item in updated.scenario["resources"] if item["resource_id"] == "boat-02")
    assert current["available"] is False
    event = store.events(created.incident_id)[-1]
    assert event["event_type"] == "report_superseded"
    assert event["payload"]["previous"]["available"] is True
    assert event["payload"]["replacement"]["available"] is False


def test_incident_store_refuses_a_tampered_event_chain(tmp_path):
    path = tmp_path / "incidents.sqlite3"
    store = IncidentStore(path)
    created = store.create(_scenario())
    store.add_report(created.incident_id, "request", _request("family-chain"))

    import sqlite3
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE incident_events SET payload_json = '{}' WHERE incident_id = ? AND revision = 2", (created.incident_id,))

    with pytest.raises(ValueError, match="event hash"):
        store.events(created.incident_id)


def test_incident_store_refuses_snapshot_not_sealed_by_ledger_tip(tmp_path):
    path = tmp_path / "incidents.sqlite3"
    store = IncidentStore(path)
    created = store.create(_scenario())
    replacement = _scenario()
    replacement["requests"] = replacement["requests"][:-1]

    import sqlite3
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE incidents SET scenario_json = ?, scenario_sha256 = ? WHERE incident_id = ?",
            (json.dumps(replacement, sort_keys=True, separators=(",", ":")), _digest(replacement), created.incident_id),
        )

    with pytest.raises(ValueError, match="not sealed by the ledger tip"):
        store.get(created.incident_id)


def test_verify_all_returns_count_for_intact_ledger(tmp_path):
    store = IncidentStore(tmp_path / "incidents.sqlite3")
    store.create(_scenario())

    assert store.verify_all() == 1


def test_incident_approval_is_bound_to_the_sealed_persisted_revision(tmp_path):
    store = IncidentStore(tmp_path / "incidents.sqlite3")
    created = store.create(_scenario())
    plan = store.plan(created.incident_id, "2026-07-17T11:00:00Z")
    assert plan["verification"]["plan_sha256"] == plan["seal"]["sha256"]
    assert plan["verification_seal"]["plan_sha256"] == plan["seal"]["sha256"]
    assert plan["verification_seal"]["sha256"] == seal_digest(plan["verification"])
    assert plan["verification"]["incident_revision"] == created.revision
    verify_payload(
        plan["verification"], plan["plan"], expected_plan_sha256=plan["seal"]["sha256"])
    proposal = next(item for item in plan["plan"]["proposals"] if item["status"] == "PROPOSED")

    entry = store.record_approval(
        created.incident_id, request_id=proposal["request_id"], action="approve", approver="anna-coordinator",
        proposal_audit_hash=proposal["audit_hash"], plan_sha256=plan["seal"]["sha256"],
        reference_time="2026-07-17T11:00:00Z",
    )
    assert entry["approver"] == "anna-coordinator"
    assert store.approvals(created.incident_id)[0]["entry_hash"] == entry["entry_hash"]

    store.add_report(created.incident_id, "request", _request("family-revision-two"))
    with pytest.raises(IncidentConflict, match="stale incident plan"):
        store.record_approval(
            created.incident_id, request_id=proposal["request_id"], action="reject", approver="anna-coordinator",
            proposal_audit_hash=proposal["audit_hash"], plan_sha256=plan["seal"]["sha256"],
            reference_time="2026-07-17T11:00:00Z",
        )


def test_incident_approval_claim_is_atomic_across_store_instances(tmp_path):
    path = tmp_path / "incidents.sqlite3"
    first = IncidentStore(path)
    second = IncidentStore(path)
    created = first.create(_scenario())
    plan = first.plan(created.incident_id, "2026-07-17T11:00:00Z")
    proposal = next(item for item in plan["plan"]["proposals"] if item["status"] == "PROPOSED")
    barrier = threading.Barrier(2)
    entries = []
    errors = []

    def record(store):
        barrier.wait(timeout=5)
        try:
            entries.append(store.record_approval(
                created.incident_id, request_id=proposal["request_id"], action="approve",
                approver="anna-coordinator", proposal_audit_hash=proposal["audit_hash"],
                plan_sha256=plan["seal"]["sha256"], reference_time="2026-07-17T11:00:00Z",
            ))
        except IncidentConflict as error:
            errors.append(error)

    threads = [threading.Thread(target=record, args=(store,)) for store in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(entries) == 1
    assert len(errors) == 1
    assert "already recorded" in str(errors[0])
    assert len(first.approvals(created.incident_id)) == 1


def test_incident_approval_claim_rolls_back_when_ledger_append_fails(tmp_path, monkeypatch):
    store = IncidentStore(tmp_path / "incidents.sqlite3")
    created = store.create(_scenario())
    plan = store.plan(created.incident_id, "2026-07-17T11:00:00Z")
    proposal = next(item for item in plan["plan"]["proposals"] if item["status"] == "PROPOSED")

    def fail_append(*args, **kwargs):
        raise ApprovalChainError("synthetic append failure")

    with monkeypatch.context() as patch:
        patch.setattr(incident_module, "append_entry", fail_append)
        with pytest.raises(IncidentStoreError, match="synthetic append failure"):
            store.record_approval(
                created.incident_id, request_id=proposal["request_id"], action="approve",
                approver="anna-coordinator", proposal_audit_hash=proposal["audit_hash"],
                plan_sha256=plan["seal"]["sha256"], reference_time="2026-07-17T11:00:00Z",
            )

    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM incident_approval_claims").fetchone()[0] == 0
    entry = store.record_approval(
        created.incident_id, request_id=proposal["request_id"], action="approve",
        approver="anna-coordinator", proposal_audit_hash=proposal["audit_hash"],
        plan_sha256=plan["seal"]["sha256"], reference_time="2026-07-17T11:00:00Z",
    )
    assert entry["index"] == 0
    assert len(store.approvals(created.incident_id)) == 1
