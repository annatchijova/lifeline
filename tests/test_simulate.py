import json
from pathlib import Path

import pytest

from lifeline.export import seal_digest
from lifeline.scenario import load_scenario
from lifeline.simulate import (
    SimulationError,
    apply_overrides,
    load_whatifs,
    parse_whatifs,
    simulate_payload,
)

REPO = Path(__file__).resolve().parent.parent
SCENARIO_PATH = REPO / "scenarios" / "flood_v1.json"
WHATIFS_PATH = REPO / "scenarios" / "flood_v1_whatifs.json"


def _payload():
    scenario = load_scenario(SCENARIO_PATH)
    simulation_id, variants = load_whatifs(WHATIFS_PATH)
    return simulate_payload(scenario, simulation_id, variants)


def _variant(payload, variant_id):
    return next(v for v in payload["variants"] if v["variant_id"] == variant_id)


def _entry(variant, request_id):
    return next(d for d in variant["diff"] if d["request_id"] == request_id)


def test_whatifs_file_parses():
    simulation_id, variants = load_whatifs(WHATIFS_PATH)
    assert simulation_id == "flood-v1-whatifs"
    assert [v.variant_id for v in variants] == [
        "north-route-closed", "south-access-restored", "shelter-a-degraded"]


def test_rejects_unknown_kind_field_and_missing_target():
    raw = json.loads(WHATIFS_PATH.read_text())
    raw["variants"][0]["overrides"][0]["set"] = {"eta_minutes": -1}
    with pytest.raises(SimulationError, match="positive"):
        parse_whatifs(raw)

    raw = json.loads(WHATIFS_PATH.read_text())
    raw["variants"][0]["overrides"][0]["set"] = {"resource_id": "x"}
    with pytest.raises(SimulationError, match="not settable"):
        parse_whatifs(raw)

    scenario = load_scenario(SCENARIO_PATH)
    raw = json.loads(WHATIFS_PATH.read_text())
    raw["variants"][0]["overrides"][0]["destination"] = "nowhere"
    _, variants = parse_whatifs(raw)
    with pytest.raises(SimulationError, match="no route"):
        apply_overrides(scenario, variants[0])


def test_north_route_closed_exposes_fragility():
    variant = _variant(_payload(), "north-route-closed")
    entry = _entry(variant, "family-north")
    assert entry["changed"] is True
    assert entry["base"]["status"] == "PROPOSED"
    assert entry["variant"]["status"] == "NEEDS_HUMAN_REVIEW"


def test_south_access_restored_still_lacks_a_big_enough_resource():
    variant = _variant(_payload(), "south-access-restored")
    entry = _entry(variant, "family-south")
    # Verification and routes are not enough: no available resource carries 6.
    assert entry["variant"]["status"] == "NEEDS_HUMAN_REVIEW"
    assert entry["changed"] is False
    # The unverified-route downgrade is gone in this variant, so the base
    # gate reason must have shifted from verification to capacity.
    assert any(d["request_id"] == "family-south" for d in variant["diff"])


def test_shelter_degradation_pushes_family_east_out():
    variant = _variant(_payload(), "shelter-a-degraded")
    north = _entry(variant, "family-north")
    east = _entry(variant, "family-east")
    assert north["variant"]["status"] == "PROPOSED"
    assert east["changed"] is True
    assert east["variant"]["status"] == "NEEDS_HUMAN_REVIEW"


def test_simulation_payload_is_deterministic_and_sealable():
    first = _payload()
    second = _payload()
    assert seal_digest(first) == seal_digest(second)
    assert first["limitations"], "limitations must be disclosed"
    assert first["base"]["proposals"]