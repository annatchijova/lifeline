import json
from pathlib import Path

from lifeline.export import export_plan, seal_digest
from lifeline.scenario import load_scenario, parse_scenario, plan_scenario
from lifeline.validators import validate_scenario
from lifeline.verification import verification_payload


REPO = Path(__file__).resolve().parent.parent
SCENARIO_PATH = REPO / "scenarios" / "flood_v1.json"


def _node(payload, request_id, reason_code):
    return next(
        node for node in payload["nodes"]
        if node["request_id"] == request_id and node["reason_code"] == reason_code
    )


def test_verification_payload_exposes_explicit_request_evidence_gaps():
    scenario, findings = validate_scenario(load_scenario(SCENARIO_PATH))
    proposals = plan_scenario(scenario)
    payload = verification_payload(scenario, proposals, findings, plan_sha256="a" * 64)

    south = _node(payload, "family-south", "REQUEST_UNVERIFIED")
    assert south["disposition"] == "BLOCKED"
    assert south["action_required"] == "VERIFY_REQUEST_REPORT"
    assert south["required_artifacts"] == ["authorized_request_confirmation"]
    assert south["supports"][0]["source"] == "radio-listener"
    assert south["supports"][0]["observation"] == "ANALYZED"
    assert south["refutes"] == []

    riverside = _node(payload, "group-riverside", "REQUEST_CONTRADICTION")
    assert riverside["action_required"] == "OBTAIN_DISCRIMINATING_EVIDENCE"
    assert riverside["required_artifacts"] == ["independent_authorized_request_confirmation"]
    assert "priority score" in payload["limitations"][0]

    north = _node(payload, "family-north", "EVIDENCE_GATES_CLEAR")
    assert north["disposition"] == "CLEAR"
    assert north["action_required"] == "HUMAN_APPROVAL_REQUIRED"
    assert north["required_artifacts"] == []
    assert {item["entity_type"] for item in north["supports"]} == {"request", "resource", "shelter", "route"}


def test_stale_request_is_blocked_and_names_fresh_evidence_needed():
    raw = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    raw["requests"][0]["freshness"] = "low"
    scenario = parse_scenario(raw)
    proposals = {item.request_id: item for item in plan_scenario(scenario)}
    assert proposals["family-north"].status == "NEEDS_HUMAN_REVIEW"
    assert "stale report" in proposals["family-north"].reasons

    payload = verification_payload(scenario, list(proposals.values()), (), plan_sha256="b" * 64)
    node = _node(payload, "family-north", "REQUEST_STALE")
    assert node["required_artifacts"] == ["fresh_authorized_request_report"]
    assert node["action_required"] == "OBTAIN_FRESH_REQUEST_REPORT"


def test_route_contradiction_keeps_the_open_and_closed_reports_visible():
    raw = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    raw["routes"].append({
        "origin": "north-bank", "destination": "shelter-a", "eta_minutes": 8, "open": False,
        "source": "patrol-09", "source_type": "responder",
        "observed_at": "2026-07-17T09:11:00Z", "verification_state": "verified", "freshness": "high",
    })
    scenario, findings = validate_scenario(parse_scenario(raw))
    payload = verification_payload(scenario, plan_scenario(scenario), findings, plan_sha256="c" * 64)

    node = _node(payload, "family-north", "ROUTE_CONTRADICTION")
    assert node["action_required"] == "OBTAIN_DISCRIMINATING_ROUTE_EVIDENCE"
    assert node["required_artifacts"] == ["independent_current_route_status"]
    assert [item["assertion"] for item in node["supports"]] == ["route_reported_open"]
    assert [item["assertion"] for item in node["refutes"]] == ["route_reported_closed"]


def test_export_seals_verification_as_a_sibling_bound_to_the_plan(tmp_path):
    result = export_plan(SCENARIO_PATH, tmp_path)
    verification = json.loads((tmp_path / "verification.json").read_text(encoding="utf-8"))
    seal = json.loads((tmp_path / "verification.seal.json").read_text(encoding="utf-8"))

    assert verification["plan_sha256"] == result.seal["sha256"]
    assert seal["plan_sha256"] == result.seal["sha256"]
    assert seal["sha256"] == seal_digest(verification)
