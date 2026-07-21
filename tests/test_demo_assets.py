import json
from pathlib import Path

from lifeline.export import seal_digest


REPO = Path(__file__).resolve().parent.parent
DEMO = REPO / "web" / "demo"


def test_bundled_demo_is_complete_and_sealed():
    required = {
        "plan.json", "plan.seal.json", "verification.json", "verification.seal.json",
        "room.geojson", "simulation.json", "simulation.seal.json",
    }
    assert required <= {path.name for path in DEMO.iterdir()}

    plan = json.loads((DEMO / "plan.json").read_text(encoding="utf-8"))
    seal = json.loads((DEMO / "plan.seal.json").read_text(encoding="utf-8"))
    verification = json.loads((DEMO / "verification.json").read_text(encoding="utf-8"))
    verification_seal = json.loads((DEMO / "verification.seal.json").read_text(encoding="utf-8"))
    room = json.loads((DEMO / "room.geojson").read_text(encoding="utf-8"))

    assert seal_digest(plan) == seal["sha256"]
    assert seal_digest(verification) == verification_seal["sha256"]
    assert verification["plan_sha256"] == seal["sha256"]
    assert room["type"] == "FeatureCollection"
    assert room["features"]


def test_browser_fallback_matches_the_sealed_demo_artifacts():
    bundle = (REPO / "web" / "demo-data.js").read_text(encoding="utf-8")
    payload = json.loads(bundle.split("=", 1)[1].rstrip(";\n"))

    assert payload["plan"] == json.loads((DEMO / "plan.json").read_text(encoding="utf-8"))
    assert payload["seal"] == json.loads((DEMO / "plan.seal.json").read_text(encoding="utf-8"))
    assert payload["verification"] == json.loads((DEMO / "verification.json").read_text(encoding="utf-8"))
    assert payload["verificationSeal"] == json.loads((DEMO / "verification.seal.json").read_text(encoding="utf-8"))
    assert payload["room"] == json.loads((DEMO / "room.geojson").read_text(encoding="utf-8"))


def test_room_defaults_to_demo_and_live_mode_has_a_demo_fallback():
    room_html = (REPO / "web" / "room.html").read_text(encoding="utf-8")
    assert 'get("mode") !== "live"' in room_html
    assert 'window.location.replace("room.html?mode=demo&missing=live")' in room_html
    assert 'VERIFICATION GRAPH — EVIDENCE BEFORE NARRATIVE' in room_html
    assert 'CONTRADICTORY OBSERVATIONS REMAIN VISIBLE' in room_html
    assert "DEMO RUN OF SHOW — THE KERNEL'S COMPLETE PATH" in room_html
    assert "AGENT BRIEFING MODE — OPTIONAL, INTERPRETIVE ONLY" in room_html
    assert "agent_briefing.json" in room_html
    assert "citationLabel" in room_html
    assert "incident_changes" in room_html
    assert "headline_citations" in room_html
    assert "summary_citations" in room_html
    assert 'verification.seal.json' in room_html
