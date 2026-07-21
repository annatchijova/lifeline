import json
from pathlib import Path

from lifeline.export import seal_digest


REPO = Path(__file__).resolve().parent.parent
DEMO = REPO / "web" / "demo"


def test_bundled_demo_is_complete_and_sealed():
    required = {
        "plan.json", "plan.seal.json", "verification.json", "verification.seal.json",
        "room.geojson", "simulation.json", "simulation.seal.json",
        "agent_briefing.json", "agent_briefing.seal.json",
    }
    assert required <= {path.name for path in DEMO.iterdir()}

    plan = json.loads((DEMO / "plan.json").read_text(encoding="utf-8"))
    seal = json.loads((DEMO / "plan.seal.json").read_text(encoding="utf-8"))
    verification = json.loads((DEMO / "verification.json").read_text(encoding="utf-8"))
    verification_seal = json.loads((DEMO / "verification.seal.json").read_text(encoding="utf-8"))
    agent = json.loads((DEMO / "agent_briefing.json").read_text(encoding="utf-8"))
    agent_seal = json.loads((DEMO / "agent_briefing.seal.json").read_text(encoding="utf-8"))
    room = json.loads((DEMO / "room.geojson").read_text(encoding="utf-8"))

    assert seal_digest(plan) == seal["sha256"]
    assert seal_digest(verification) == verification_seal["sha256"]
    assert verification["plan_sha256"] == seal["sha256"]
    assert seal_digest(agent) == agent_seal["sha256"]
    assert agent["plan_sha256"] == seal["sha256"]
    assert agent["verification_sha256"] == verification_seal["sha256"]
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
    assert payload["agent"] == json.loads((DEMO / "agent_briefing.json").read_text(encoding="utf-8"))
    assert payload["agentSeal"] == json.loads((DEMO / "agent_briefing.seal.json").read_text(encoding="utf-8"))


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
    assert "agent_briefing_version !== 5" in room_html
    assert "sealBound" in room_html
    assert "state.agentSeal.seal_version === 3" in room_html
    assert 'verification.seal.json' in room_html


def test_static_landing_explains_the_working_prototype_and_agent_boundary():
    landing = (REPO / "web" / "index.html").read_text(encoding="utf-8")

    assert "Built as a system, not a mock-up." in landing
    assert "Ten ideas. Three became one." in landing
    assert "10,000+ tracked code lines" in landing
    assert "5,300+ Python LOC" in landing
    assert "100+ regression tests" in landing
    assert "focused red-team rounds" in landing
    assert "Optional agent boundary" in landing
    assert "selects opaque citations only" in landing
    assert "no authority to alter an incident, plan, approval, alert, or dispatch state" in landing
    assert "A real agent run, visible without an API." in landing
    assert "CAPTURED LOCAL AGENT BRIEFING" in landing
    assert "nvidia_chat_completions · meta/llama-3.1-8b-instruct" in landing
    assert "Sealed incident: 0 proposal(s) await a human decision; 4 require evidence review." in landing
    assert "REQUEST_CONTRADICTION · OBTAIN_DISCRIMINATING_EVIDENCE" in landing
