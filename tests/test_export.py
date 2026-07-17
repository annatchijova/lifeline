import json
import subprocess
import sys
from pathlib import Path

import pytest

from lifeline.export import CanonicalizationError, canonicalize, export_plan, seal_digest

REPO = Path(__file__).resolve().parent.parent
SCENARIO_PATH = REPO / "scenarios" / "flood_v1.json"


def _run_cli(scenario: Path, out_dir: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "lifeline", "plan", str(scenario), "--out", str(out_dir)],
        cwd=REPO, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_canonicalization_rejects_floats_and_distinguishes_types():
    with pytest.raises(CanonicalizationError, match="float"):
        canonicalize({"value": 0.5})
    assert seal_digest(1) != seal_digest("1")
    assert seal_digest(1) != seal_digest(True)
    assert seal_digest({"a": 1, "b": 2}) == seal_digest({"b": 2, "a": 1})


def test_export_is_deterministic_across_fresh_processes_and_input_order(tmp_path):
    raw = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    shuffled = dict(raw)
    for key in ("zones", "requests", "resources", "shelters", "routes"):
        shuffled[key] = list(reversed(raw[key]))
    shuffled_path = tmp_path / "shuffled.json"
    shuffled_path.write_text(json.dumps(shuffled), encoding="utf-8")

    outputs = []
    for name, scenario in (("a", SCENARIO_PATH), ("b", SCENARIO_PATH), ("c", shuffled_path)):
        out_dir = tmp_path / name
        _run_cli(scenario, out_dir)
        outputs.append((
            (out_dir / "plan.json").read_bytes(),
            json.loads((out_dir / "plan.seal.json").read_text())["sha256"],
        ))

    assert outputs[0] == outputs[1]
    assert outputs[0][0] == outputs[2][0]
    assert outputs[0][1] == outputs[2][1]


def test_sealed_plan_contains_no_floats(tmp_path):
    export_plan(SCENARIO_PATH, tmp_path)
    plan = json.loads((tmp_path / "plan.json").read_text())

    def walk(value):
        assert not isinstance(value, float), f"float found in sealed plan: {value}"
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(plan)


def test_room_geojson_carries_provenance_and_gated_outcomes(tmp_path):
    export_plan(SCENARIO_PATH, tmp_path)
    room = json.loads((tmp_path / "room.geojson").read_text())
    by_type = {}
    for feature in room["features"]:
        by_type.setdefault(feature["properties"]["feature_type"], []).append(feature)

    assert {"zone", "request", "resource", "shelter", "route"} <= set(by_type)
    south = next(f for f in by_type["request"] if f["properties"]["request_id"] == "family-south")
    assert south["properties"]["status"] == "NEEDS_HUMAN_REVIEW"
    assert south["properties"]["verification_state"] == "unverified"
    conflicting_route = next(
        f for f in by_type["route"] if f["properties"]["verification_state"] == "conflicting")
    assert conflicting_route["properties"]["reported_open"] is True
    assert conflicting_route["properties"]["usable"] is False
