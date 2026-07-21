import json
from pathlib import Path

import pytest

from lifeline.scenario import load_scenario, parse_scenario, plan_scenario
from lifeline.validators import validate_scenario

SCENARIO_PATH = Path(__file__).resolve().parent.parent / "scenarios" / "flood_v1.json"


def _raw():
    return json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))


def _codes(findings):
    return [finding.code for finding in findings]


def test_no_reference_time_reports_staleness_unchecked():
    _, findings = validate_scenario(load_scenario(SCENARIO_PATH))
    assert "STALENESS_UNCHECKED" in _codes(findings)


def test_contradictory_route_reports_are_downgraded_and_block_planning():
    raw = _raw()
    # Second report for the same leg disagreeing on open state.
    raw["routes"].append({
        "origin": "north-bank", "destination": "shelter-a", "eta_minutes": 8, "open": False,
        "source": "patrol-09", "source_type": "responder",
        "observed_at": "2026-07-17T09:11:00Z", "verification_state": "verified", "freshness": "high",
    })
    scenario, findings = validate_scenario(parse_scenario(raw))
    assert "ROUTE_CONTRADICTION" in _codes(findings)
    states = {r.provenance.verification_state for r in scenario.routes
              if r.route.origin == "north-bank" and r.route.destination == "shelter-a"}
    assert states == {"conflicting"}

    plan = plan_scenario(scenario)
    by_id = {p.request_id: p for p in plan}
    assert by_id["family-north"].status == "NEEDS_HUMAN_REVIEW"


def test_duplicate_requests_downgrade_the_later_report():
    raw = _raw()
    raw["requests"].append({
        "request_id": "family-north-again", "people": 4, "urgency": 5, "medical_need": False,
        "pickup_zone": "north-bank", "destination_zone": "shelter-a",
        "source": "operator-02", "source_type": "verified_operator",
        "observed_at": "2026-07-17T09:20:00Z", "verification_state": "verified", "freshness": "high",
    })
    scenario, findings = validate_scenario(parse_scenario(raw))
    duplicates = [f for f in findings if f.code == "POSSIBLE_DUPLICATE"]
    assert len(duplicates) == 1
    assert duplicates[0].entity_id == "family-north-again"

    by_id = {r.request.request_id: r for r in scenario.requests}
    assert by_id["family-north"].provenance.verification_state == "verified"
    assert by_id["family-north-again"].provenance.verification_state == "unverified"

    plan = {p.request_id: p for p in plan_scenario(scenario)}
    assert plan["family-north"].status == "PROPOSED"
    assert plan["family-north-again"].status == "NEEDS_HUMAN_REVIEW"


def test_staleness_downgrades_freshness_with_reference_time():
    scenario, findings = validate_scenario(
        load_scenario(SCENARIO_PATH), reference_time="2026-07-17T13:30:00Z")
    stale = [f for f in findings if f.code == "STALE_REPORT"]
    assert stale, "expected stale findings four+ hours after observation"
    by_id = {r.request.request_id: r for r in scenario.requests}
    # Observed 09:12, reference 13:30 -> 258 minutes -> low.
    assert by_id["family-north"].provenance.freshness == "low"
    # Downgrade only: nothing may become fresher than declared.
    for reported in scenario.requests:
        assert reported.provenance.freshness in ("high", "medium", "low")
    assert "STALENESS_UNCHECKED" not in _codes(findings)


def test_reference_time_without_timezone_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        validate_scenario(load_scenario(SCENARIO_PATH), reference_time="2026-07-17T13:30:00")


def test_future_or_unparseable_operational_timestamps_are_downgraded_not_used():
    raw = _raw()
    raw["resources"][0]["observed_at"] = "2026-07-17T14:00:00Z"
    raw["shelters"][0]["observed_at"] = "not-a-timestamp"

    scenario, findings = validate_scenario(
        parse_scenario(raw), reference_time="2026-07-17T13:30:00Z")
    by_resource = {item.resource.resource_id: item for item in scenario.resources}
    by_shelter = {item.shelter.shelter_id: item for item in scenario.shelters}

    assert by_resource["boat-02"].provenance.freshness == "low"
    assert by_shelter["shelter-a"].provenance.freshness == "low"
    assert {"FUTURE_TIMESTAMP", "UNPARSEABLE_TIMESTAMP"} <= set(_codes(findings))

    plan = {proposal.request_id: proposal for proposal in plan_scenario(scenario)}
    assert plan["family-north"].status == "NEEDS_HUMAN_REVIEW"


def test_subsecond_future_request_is_downgraded_before_planning():
    raw = _raw()
    raw["requests"][0]["observed_at"] = "2026-07-17T11:00:00.500000+00:00"

    scenario, findings = validate_scenario(
        parse_scenario(raw), reference_time="2026-07-17T11:00:00+00:00")
    request = next(item for item in scenario.requests if item.request.request_id == "family-north")
    proposal = next(item for item in plan_scenario(scenario) if item.request_id == "family-north")

    assert request.provenance.freshness == "low"
    assert "FUTURE_TIMESTAMP" in _codes(findings)
    assert proposal.status == "NEEDS_HUMAN_REVIEW"


def test_findings_are_deterministically_ordered():
    a = validate_scenario(load_scenario(SCENARIO_PATH), reference_time="2026-07-17T13:30:00Z")[1]
    b = validate_scenario(load_scenario(SCENARIO_PATH), reference_time="2026-07-17T13:30:00Z")[1]
    assert [f.as_dict() for f in a] == [f.as_dict() for f in b]
