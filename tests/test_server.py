import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from lifeline.export import export_plan
from lifeline.server import make_server

REPO = Path(__file__).resolve().parent.parent
SCENARIO_PATH = REPO / "scenarios" / "flood_v1.json"


@pytest.fixture()
def room(tmp_path):
    out_dir = tmp_path / "out"
    export_plan(SCENARIO_PATH, out_dir)
    server = make_server(REPO, out_dir, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    plan = json.loads((out_dir / "plan.json").read_text())
    seal = json.loads((out_dir / "plan.seal.json").read_text())
    yield base, plan, seal, out_dir
    server.shutdown()
    server.server_close()


def _post(base, payload):
    request = urllib.request.Request(
        f"{base}/api/approvals",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def _post_to(base, path, payload):
    request = urllib.request.Request(
        f"{base}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def _get(base, path):
    try:
        with urllib.request.urlopen(f"{base}{path}") as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, b""


def _get_json(base, path):
    request = urllib.request.Request(f"{base}{path}")
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def _proposed(plan):
    return next(p for p in plan["proposals"] if p["status"] == "PROPOSED")


def test_records_approval_and_rejects_duplicate(room):
    base, plan, seal, out_dir = room
    proposal = _proposed(plan)
    payload = {
        "request_id": proposal["request_id"],
        "action": "approve",
        "approver": "coordinator-1",
        "proposal_audit_hash": proposal["audit_hash"],
        "plan_sha256": seal["sha256"],
    }
    status, body = _post(base, payload)
    assert status == 201
    assert body["entry"]["request_id"] == proposal["request_id"]
    assert (out_dir / "approvals.jsonl").exists()

    status, body = _post(base, payload)
    assert status == 409
    assert "already recorded" in body["error"]

    status, listing = _get(base, "/api/approvals")
    assert status == 200
    listing = json.loads(listing)
    assert listing["chain_ok"] is True
    assert len(listing["entries"]) == 1


def test_rejects_stale_plan_and_stale_proposal(room):
    base, plan, seal, _ = room
    proposal = _proposed(plan)
    status, body = _post(base, {
        "request_id": proposal["request_id"], "action": "approve", "approver": "c1",
        "proposal_audit_hash": proposal["audit_hash"], "plan_sha256": "not-the-plan",
    })
    assert status == 409 and "stale plan" in body["error"]
    status, body = _post(base, {
        "request_id": proposal["request_id"], "action": "approve", "approver": "c1",
        "proposal_audit_hash": "wrong", "plan_sha256": seal["sha256"],
    })
    assert status == 409 and "stale proposal" in body["error"]


def test_rejects_decisions_on_gated_items_and_bad_input(room):
    base, plan, seal, _ = room
    gated = next(p for p in plan["proposals"] if p["status"] == "NEEDS_HUMAN_REVIEW")
    status, body = _post(base, {
        "request_id": gated["request_id"], "action": "approve", "approver": "c1",
        "proposal_audit_hash": gated["audit_hash"], "plan_sha256": seal["sha256"],
    })
    assert status == 409 and "PROPOSED" in body["error"]

    proposal = _proposed(plan)
    status, body = _post(base, {
        "request_id": proposal["request_id"], "action": "dispatch", "approver": "c1",
        "proposal_audit_hash": proposal["audit_hash"], "plan_sha256": seal["sha256"],
    })
    assert status == 400

    status, body = _post(base, {"action": "approve"})
    assert status == 400


def test_static_scope_is_restricted(room):
    base, _, seal, _ = room
    status, _ = _get(base, "/")
    assert status == 200
    assert _get(base, "/web/room.html")[0] == 200
    status, body = _get(base, "/out/plan.seal.json")
    assert status == 200 and json.loads(body)["sha256"] == seal["sha256"]
    status, body = _get(base, "/web/demo/plan.seal.json")
    assert status == 200 and "sha256" in json.loads(body)
    assert _get(base, "/.git/config")[0] == 404
    assert _get(base, "/web/../.git/config")[0] == 404
    assert _get(base, "/lifeline/core.py")[0] == 404


def test_incident_api_creates_searches_appends_and_plans(room):
    base, _, _, _ = room
    scenario = json.loads(SCENARIO_PATH.read_text())
    status, created = _post_to(base, "/api/incidents", scenario)
    assert status == 201
    assert created["revision"] == 1

    status, listing = _get_json(base, "/api/incidents?q=flood-v1")
    assert status == 200
    assert listing["incidents"][0]["incident_id"] == "flood-v1-synthetic"

    request = {
        "request_id": "family-api", "people": 2, "urgency": 4, "medical_need": False,
        "pickup_zone": "north-bank", "destination_zone": "shelter-a",
        "source": "operator-api", "source_type": "verified_operator",
        "observed_at": "2026-07-17T10:00:00Z", "verification_state": "verified", "freshness": "high",
    }
    status, updated = _post_to(base, "/api/incidents/flood-v1-synthetic/reports", {
        "entity_type": "request", "report": request,
    })
    assert status == 201 and updated["revision"] == 2

    corrected_boat = scenario["resources"][0] | {"available": False, "observed_at": "2026-07-17T10:30:00Z"}
    status, corrected = _post_to(base, "/api/incidents/flood-v1-synthetic/corrections", {
        "entity_type": "resource", "report": corrected_boat,
    })
    assert status == 201 and corrected["revision"] == 3

    status, events = _get_json(base, "/api/incidents/flood-v1-synthetic/events?after_revision=1")
    assert status == 200 and [event["event_type"] for event in events["events"]] == ["report_added", "report_superseded"]

    status, alerts = _get_json(base, "/api/incidents/flood-v1-synthetic/alerts?after_revision=2")
    assert status == 200
    assert any(alert["code"] == "REPORT_SUPERSEDED" for alert in alerts["alerts"])
    assert all(alert["dispatch_authority"] == "none" for alert in alerts["alerts"])

    status, planned = _post_to(base, "/api/incidents/flood-v1-synthetic/plan", {
        "reference_time": "2026-07-17T11:00:00Z",
    })
    assert status == 200
    assert planned["revision"] == 3 and planned["seal"]["sha256"]
