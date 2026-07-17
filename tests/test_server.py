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


def _get(base, path):
    try:
        with urllib.request.urlopen(f"{base}{path}") as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, b""


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
    assert _get(base, "/web/room.html")[0] == 200
    status, body = _get(base, "/out/plan.seal.json")
    assert status == 200 and json.loads(body)["sha256"] == seal["sha256"]
    assert _get(base, "/.git/config")[0] == 404
    assert _get(base, "/web/../.git/config")[0] == 404
    assert _get(base, "/lifeline/core.py")[0] == 404
