import json
from pathlib import Path

import pytest

from lifeline.scenario import ScenarioError, load_scenario, parse_scenario, plan_scenario

SCENARIO_PATH = Path(__file__).resolve().parent.parent / "scenarios" / "flood_v1.json"


def _raw():
    return json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))


def test_flood_scenario_loads():
    scenario = load_scenario(SCENARIO_PATH)
    assert scenario.scenario_id == "flood-v1-synthetic"
    assert len(scenario.zones) == 7
    assert len(scenario.requests) == 4


def test_rejects_unknown_schema_version():
    raw = _raw()
    raw["schema_version"] = 2
    with pytest.raises(ScenarioError, match="schema_version"):
        parse_scenario(raw)


def test_rejects_unknown_zone_reference():
    raw = _raw()
    raw["requests"][0]["pickup_zone"] = "nowhere"
    with pytest.raises(ScenarioError, match="unknown zone 'nowhere'"):
        parse_scenario(raw)


def test_rejects_out_of_range_coordinates():
    raw = _raw()
    raw["zones"][0]["display"]["lat"] = 91.0
    with pytest.raises(ScenarioError, match="out of range"):
        parse_scenario(raw)


def test_rejects_unknown_verification_state():
    raw = _raw()
    raw["requests"][0]["verification_state"] = "trusted"
    with pytest.raises(ScenarioError, match="verification_state"):
        parse_scenario(raw)


def test_rejects_duplicate_ids():
    raw = _raw()
    raw["resources"][1]["resource_id"] = raw["resources"][0]["resource_id"]
    with pytest.raises(ScenarioError, match="duplicate id"):
        parse_scenario(raw)


def test_rejects_non_positive_people_and_boolean_integers():
    raw = _raw()
    raw["requests"][0]["people"] = 0
    with pytest.raises(ScenarioError, match="must be positive"):
        parse_scenario(raw)
    raw = _raw()
    raw["requests"][0]["urgency"] = True
    with pytest.raises(ScenarioError, match="must be an integer"):
        parse_scenario(raw)


def test_unverified_and_conflicting_requests_are_gated_not_planned():
    plan = plan_scenario(load_scenario(SCENARIO_PATH))
    by_id = {proposal.request_id: proposal for proposal in plan}

    assert by_id["family-south"].status == "NEEDS_HUMAN_REVIEW"
    assert "unverified report" in by_id["family-south"].reasons
    assert by_id["group-riverside"].status == "NEEDS_HUMAN_REVIEW"
    assert "conflicting reports" in by_id["group-riverside"].reasons

    assert by_id["family-north"].status == "PROPOSED"
    assert by_id["family-north"].resource_id == "boat-02"
    assert by_id["family-north"].eta_minutes == 19
    assert by_id["family-east"].status == "PROPOSED"
    assert by_id["family-east"].resource_id == "ambulance-01"
    assert by_id["family-east"].eta_minutes == 21


def test_non_verified_route_is_unusable_even_if_reported_open():
    raw = _raw()
    # Make family-south verified; its only outbound route stays unverified.
    raw["requests"][2]["verification_state"] = "verified"
    # Reopen the inbound leg so only the unverified route blocks the plan.
    raw["routes"][4]["open"] = True
    plan = plan_scenario(parse_scenario(raw))
    by_id = {proposal.request_id: proposal for proposal in plan}
    assert by_id["family-south"].status == "NEEDS_HUMAN_REVIEW"
    assert "no reachable shelter capacity" in by_id["family-south"].reasons


def test_stale_route_is_unusable_even_if_open_and_verified():
    raw = _raw()
    # north-bank -> shelter-a becomes stale; family-north loses its only outbound leg.
    raw["routes"][1]["freshness"] = "low"
    plan = {p.request_id: p for p in plan_scenario(parse_scenario(raw))}
    assert plan["family-north"].status == "NEEDS_HUMAN_REVIEW"
    assert "no reachable shelter capacity" in plan["family-north"].reasons


def test_plan_is_ordered_by_urgency_across_gated_and_planned():
    plan = plan_scenario(load_scenario(SCENARIO_PATH))
    assert [proposal.request_id for proposal in plan] == [
        "family-north",
        "family-south",
        "family-east",
        "group-riverside",
    ]
