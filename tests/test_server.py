import json
import os
import socket
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from lifeline.export import export_plan
from lifeline.auth import OperatorStore
from lifeline.server import make_server, serve

REPO = Path(__file__).resolve().parent.parent
SCENARIO_PATH = REPO / "scenarios" / "flood_v1.json"


@pytest.fixture()
def room(tmp_path):
    out_dir = tmp_path / "out"
    export_plan(SCENARIO_PATH, out_dir)
    _, token = OperatorStore(out_dir / "operators.sqlite3").bootstrap("test-admin")
    server = make_server(REPO, out_dir, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    plan = json.loads((out_dir / "plan.json").read_text())
    seal = json.loads((out_dir / "plan.seal.json").read_text())
    yield base, plan, seal, out_dir, token
    server.shutdown()
    server.server_close()


def _post(base, payload, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{base}/api/approvals",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def _post_to(base, path, payload, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{base}{path}", data=json.dumps(payload).encode(),
        headers=headers, method="POST",
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


def _head(base, path):
    request = urllib.request.Request(f"{base}{path}", method="HEAD")
    try:
        with urllib.request.urlopen(request) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def _get_json(base, path, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(f"{base}{path}", headers=headers)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def _proposed(plan):
    return next(p for p in plan["proposals"] if p["status"] == "PROPOSED")


def test_agent_briefing_endpoint_requires_a_coordinator_before_any_provider_call(room, monkeypatch):
    base, _, _, _, _ = room
    called = False

    def forbidden_provider(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider must not run before authentication")

    monkeypatch.setattr("lifeline.agent.narrate_incident_plan", forbidden_provider)
    status, body = _post_to(
        base, "/api/incidents/not-disclosed/agent-briefing", {"reference_time": "2026-07-17T11:00:00Z"})

    assert status == 401
    assert "bearer token" in body["error"]
    assert called is False


def test_agent_briefing_endpoint_returns_a_sealed_read_only_interpretation(room, monkeypatch):
    from lifeline.agent import agent_artifact, agent_seal, briefing_packet, verified_inputs_from_incident_plan

    base, _, _, _, token = room
    scenario = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    status, created = _post_to(base, "/api/incidents", scenario, token)
    assert status == 201
    incident_id = created["incident_id"]
    before_status, before = _get_json(base, f"/api/incidents/{incident_id}", token)
    assert before_status == 200
    observed_models = []

    observed_events = []

    def fake_narration(result, *, model, incident_events=()):
        observed_models.append(model)
        observed_events.extend(incident_events)
        inputs = verified_inputs_from_incident_plan(result)
        packet = briefing_packet(inputs, incident_events=incident_events)
        citation = packet["citations"][0]["id"]
        guide = {
            "focus_citations": [citation],
            "question_citations": [citation],
            "authority_boundary": "INTERPRETIVE_ONLY",
        }
        artifact = agent_artifact(inputs, packet, guide, model=model)
        return artifact, agent_seal(artifact)

    monkeypatch.setattr("lifeline.agent.narrate_incident_plan", fake_narration)
    status, body = _post_to(
        base, f"/api/incidents/{incident_id}/agent-briefing",
        {"reference_time": "2026-07-17T11:00:00Z", "model": "browser-controlled-model"}, token)

    assert status == 200
    assert body["agent_briefing"]["authority_boundary"] == "INTERPRETIVE_ONLY"
    assert body["agent_briefing_seal"]["sha256"]
    assert observed_models == ["gpt-5"]
    assert body["after_revision"] == 0
    assert [event["event_type"] for event in observed_events] == ["incident_created"]
    after_status, after = _get_json(base, f"/api/incidents/{incident_id}", token)
    assert after_status == 200
    assert after["revision"] == before["revision"]


def test_agent_briefing_rejects_an_event_cursor_beyond_the_current_revision(room):
    base, _, _, _, token = room
    scenario = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    status, created = _post_to(base, "/api/incidents", scenario, token)
    assert status == 201

    status, body = _post_to(
        base,
        f"/api/incidents/{created['incident_id']}/agent-briefing",
        {"reference_time": "2026-07-17T11:00:00Z", "after_revision": 2}, token)

    assert status == 400
    assert "cannot exceed" in body["error"]


def _raw_approval_request(base, token, content_length: str) -> bytes:
    port = int(base.rsplit(":", 1)[1])
    request = (
        "POST /api/approvals HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{port}\r\n"
        f"Authorization: Bearer {token}\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {content_length}\r\n"
        "Connection: close\r\n\r\n{}"
    ).encode("ascii")
    with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
        client.sendall(request)
        return _receive_all(client)


def _receive_all(client: socket.socket) -> bytes:
    chunks = []
    while chunk := client.recv(4096):
        chunks.append(chunk)
    return b"".join(chunks)


def _incomplete_unauthenticated_report_request(base) -> bytes:
    port = int(base.rsplit(":", 1)[1])
    request = (
        "POST /api/incidents/not-disclosed/reports HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{port}\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: 2\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
        client.settimeout(0.5)
        client.sendall(request)
        return _receive_all(client)


def test_records_approval_and_rejects_duplicate(room):
    base, plan, seal, out_dir, token = room
    proposal = _proposed(plan)
    payload = {
        "request_id": proposal["request_id"],
        "action": "approve",
        "approver": "test-admin",
        "proposal_audit_hash": proposal["audit_hash"],
        "plan_sha256": seal["sha256"],
    }
    status, body = _post(base, payload, token)
    assert status == 201
    assert body["entry"]["request_id"] == proposal["request_id"]
    assert (out_dir / "approvals.jsonl").exists()

    status, body = _post(base, payload, token)
    assert status == 409
    assert "already recorded" in body["error"]

    status, listing = _get_json(base, "/api/approvals", token)
    assert status == 200
    assert listing["chain_ok"] is True
    assert len(listing["entries"]) == 1


def test_rejects_non_numeric_content_length_with_a_controlled_response(room):
    base, _, _, _, token = room
    response = _raw_approval_request(base, token, "definitely-not-a-number")

    assert response.startswith(b"HTTP/1.0 400")
    assert b"Content-Length must be an integer" in response


def test_unauthenticated_incident_report_is_rejected_before_reading_its_body(room):
    base, _, _, _, _ = room
    response = _incomplete_unauthenticated_report_request(base)

    assert response.startswith(b"HTTP/1.0 401")
    assert b"a bearer token is required" in response


def test_authenticated_incomplete_body_times_out_instead_of_holding_a_handler(tmp_path):
    out_dir = tmp_path / "out"
    export_plan(SCENARIO_PATH, out_dir)
    _, token = OperatorStore(out_dir / "operators.sqlite3").bootstrap("timeout-auditor")
    server = make_server(REPO, out_dir, port=0)
    server.request_timeout_seconds = 0.1
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    request = (
        "POST /api/approvals HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{port}\r\n"
        f"Authorization: Bearer {token}\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: 2\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
            client.settimeout(0.5)
            client.sendall(request)
            response = _receive_all(client)
    finally:
        server.shutdown()
        server.server_close()

    assert response.startswith(b"HTTP/1.0 408")
    assert b"request body timed out" in response


def test_rejects_stale_plan_and_stale_proposal(room):
    base, plan, seal, _, token = room
    proposal = _proposed(plan)
    status, body = _post(base, {
        "request_id": proposal["request_id"], "action": "approve", "approver": "test-admin",
        "proposal_audit_hash": proposal["audit_hash"], "plan_sha256": "not-the-plan",
    }, token)
    assert status == 409 and "stale plan" in body["error"]
    status, body = _post(base, {
        "request_id": proposal["request_id"], "action": "approve", "approver": "test-admin",
        "proposal_audit_hash": "wrong", "plan_sha256": seal["sha256"],
    }, token)
    assert status == 409 and "stale proposal" in body["error"]


def test_refuses_a_truncated_export_without_recording_an_approval(room):
    base, plan, seal, out_dir, token = room
    proposal = _proposed(plan)
    (out_dir / "plan.json").write_text('{"partial":', encoding="utf-8")

    status, body = _post(base, {
        "request_id": proposal["request_id"], "action": "approve", "approver": "test-admin",
        "proposal_audit_hash": proposal["audit_hash"], "plan_sha256": seal["sha256"],
    }, token)

    assert status == 500
    assert body["error"] == "exported plan artifacts are unreadable; refusing to record approvals"
    assert not (out_dir / "approvals.jsonl").exists()


def test_refuses_an_interrupted_reexport_with_mixed_plan_and_seal_generations(room, monkeypatch):
    base, plan, seal, out_dir, token = room
    proposal = _proposed(plan)
    original_replace = Path.replace

    def fail_seal_publish(source, target):
        if Path(target).name == "plan.seal.json":
            raise OSError("synthetic interruption after plan publish")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_seal_publish)
    with pytest.raises(OSError, match="synthetic interruption after plan publish"):
        export_plan(SCENARIO_PATH, out_dir, reference_time="2026-07-17T11:00:00Z")

    status, body = _post(base, {
        "request_id": proposal["request_id"], "action": "approve", "approver": "test-admin",
        "proposal_audit_hash": proposal["audit_hash"], "plan_sha256": seal["sha256"],
    }, token)

    assert status == 500
    assert body["error"] == "plan.json does not match plan.seal.json; refusing to record approvals"
    assert not (out_dir / "approvals.jsonl").exists()


def test_rejects_decisions_on_gated_items_and_bad_input(room):
    base, plan, seal, _, token = room
    gated = next(p for p in plan["proposals"] if p["status"] == "NEEDS_HUMAN_REVIEW")
    status, body = _post(base, {
        "request_id": gated["request_id"], "action": "approve", "approver": "test-admin",
        "proposal_audit_hash": gated["audit_hash"], "plan_sha256": seal["sha256"],
    }, token)
    assert status == 409 and "PROPOSED" in body["error"]

    proposal = _proposed(plan)
    status, body = _post(base, {
        "request_id": proposal["request_id"], "action": "dispatch", "approver": "test-admin",
        "proposal_audit_hash": proposal["audit_hash"], "plan_sha256": seal["sha256"],
    }, token)
    assert status == 400

    status, body = _post(base, {"action": "approve"}, token)
    assert status == 400


def test_incident_api_requires_token_and_approval_uses_authenticated_operator(room):
    base, plan, seal, _, token = room
    assert _get_json(base, "/api/incidents")[0] == 401
    assert _post_to(base, "/api/incidents", json.loads(SCENARIO_PATH.read_text()))[0] == 401

    proposal = _proposed(plan)
    status, body = _post(base, {
        "request_id": proposal["request_id"], "action": "approve", "approver": "spoofed",
        "proposal_audit_hash": proposal["audit_hash"], "plan_sha256": seal["sha256"],
    }, token)
    assert status == 403 and "does not match" in body["error"]


def test_static_scope_is_restricted(room):
    base, _, seal, _, _ = room
    status, _ = _get(base, "/")
    assert status == 200
    assert _get(base, "/web/room.html")[0] == 200
    status, body = _get(base, "/out/plan.seal.json")
    assert status == 200 and json.loads(body)["sha256"] == seal["sha256"]
    assert _head(base, "/out/plan.seal.json") == 200
    assert _head(base, "/out/operators.sqlite3") == 404
    status, body = _get(base, "/out/verification.json")
    assert status == 200 and json.loads(body)["plan_sha256"] == seal["sha256"]
    status, body = _get(base, "/web/demo/plan.seal.json")
    assert status == 200 and "sha256" in json.loads(body)
    assert _get(base, "/.git/config")[0] == 404
    assert _get(base, "/web/../.git/config")[0] == 404
    assert _get(base, "/lifeline/core.py")[0] == 404


def test_public_artifacts_reject_symlinks_for_get_and_head(room, tmp_path):
    base, _, _, out_dir, _ = room
    target = tmp_path / "synthetic-server-readable.txt"
    target.write_text("LIFELINE_AUDIT_SYNTHETIC_SECRET", encoding="utf-8")
    (out_dir / "plan.json").unlink()
    os.symlink(target, out_dir / "plan.json")

    assert _get(base, "/out/plan.json")[0] == 404
    assert _head(base, "/out/plan.json") == 404


def test_public_artifacts_reject_fifos_without_blocking(room):
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO files are unavailable on this platform")
    base, _, _, out_dir, _ = room
    (out_dir / "plan.json").unlink()
    os.mkfifo(out_dir / "plan.json")

    assert _get(base, "/out/plan.json")[0] == 404
    assert _head(base, "/out/plan.json") == 404


def test_web_static_files_reject_symlinks_for_get_and_head(room, tmp_path):
    _, _, _, out_dir, _ = room
    root = tmp_path / "synthetic-root"
    web = root / "web"
    web.mkdir(parents=True)
    (root / "private.txt").write_text("LIFELINE_ENCODED_TRAVERSAL_SYNTHETIC_SECRET", encoding="utf-8")
    target = tmp_path / "synthetic-server-readable.txt"
    target.write_text("LIFELINE_WEB_SYMLINK_SYNTHETIC_SECRET", encoding="utf-8")
    os.symlink(target, web / "linked.txt")
    outside = tmp_path / "synthetic-outside"
    outside.mkdir()
    (outside / "nested-secret.txt").write_text("LIFELINE_WEB_NESTED_SYMLINK_SYNTHETIC_SECRET", encoding="utf-8")
    os.symlink(outside, web / "linked-dir", target_is_directory=True)
    server = make_server(root, out_dir, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert _get(base, "/web/linked.txt")[0] == 404
        assert _head(base, "/web/linked.txt") == 404
        assert _get(base, "/web/linked-dir/nested-secret.txt")[0] == 404
        assert _head(base, "/web/linked-dir/nested-secret.txt") == 404
        assert _get(base, "/web/%2e%2e/private.txt")[0] == 404
        assert _head(base, "/web/%2e%2e/private.txt") == 404
        assert _get(base, "/web/%00")[0] == 404
        assert _head(base, "/web/%00") == 404
    finally:
        server.shutdown()
        server.server_close()


def test_serve_describes_the_actual_local_authentication_boundary(monkeypatch, capsys, tmp_path):
    class FakeServer:
        approvals_path = tmp_path / "approvals.jsonl"

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass

    monkeypatch.setattr("lifeline.server.make_server", lambda *args, **kwargs: FakeServer())
    serve(tmp_path, tmp_path)

    output = capsys.readouterr().out
    assert "bearer-token authentication is required" in output
    assert "no authentication" not in output


def test_incident_api_creates_searches_appends_and_plans(room):
    base, _, _, _, token = room
    scenario = json.loads(SCENARIO_PATH.read_text())
    status, created = _post_to(base, "/api/incidents", scenario, token)
    assert status == 201
    assert created["revision"] == 1

    status, listing = _get_json(base, "/api/incidents?q=flood-v1", token)
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
    }, token)
    assert status == 201 and updated["revision"] == 2

    corrected_boat = scenario["resources"][0] | {"available": False, "observed_at": "2026-07-17T10:30:00Z"}
    status, corrected = _post_to(base, "/api/incidents/flood-v1-synthetic/corrections", {
        "entity_type": "resource", "report": corrected_boat,
    }, token)
    assert status == 201 and corrected["revision"] == 3

    status, events = _get_json(base, "/api/incidents/flood-v1-synthetic/events?after_revision=1", token)
    assert status == 200 and [event["event_type"] for event in events["events"]] == ["report_added", "report_superseded"]

    status, alerts = _get_json(base, "/api/incidents/flood-v1-synthetic/alerts?after_revision=2", token)
    assert status == 200
    assert any(alert["code"] == "REPORT_SUPERSEDED" for alert in alerts["alerts"])
    assert all(alert["dispatch_authority"] == "none" for alert in alerts["alerts"])

    status, planned = _post_to(base, "/api/incidents/flood-v1-synthetic/plan", {
        "reference_time": "2026-07-17T11:00:00Z",
    }, token)
    assert status == 200
    assert planned["revision"] == 3 and planned["seal"]["sha256"]
    assert planned["verification"]["plan_sha256"] == planned["seal"]["sha256"]
    assert planned["verification_seal"]["sha256"]

    proposal = _proposed(planned["plan"])
    status, recorded = _post_to(base, "/api/incidents/flood-v1-synthetic/approvals", {
        "request_id": proposal["request_id"], "action": "approve",
        "proposal_audit_hash": proposal["audit_hash"], "plan_sha256": planned["seal"]["sha256"],
        "reference_time": "2026-07-17T11:00:00Z",
    }, token)
    assert status == 201 and recorded["entry"]["approver"] == "test-admin"

    status, approvals = _get_json(base, "/api/incidents/flood-v1-synthetic/approvals", token)
    assert status == 200 and approvals["chain_ok"] is True and len(approvals["entries"]) == 1
