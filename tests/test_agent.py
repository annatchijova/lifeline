import json
from pathlib import Path
import subprocess
import sys

import pytest

from lifeline.agent import (
    AUTHORITY_BOUNDARY,
    AgentBriefingError,
    agent_artifact,
    briefing_packet,
    load_verified_inputs,
    narrate_export,
    openai_narrate,
    openai_request_body,
    narrate_incident_plan,
    validate_narration,
    verify_agent_artifact,
    verified_inputs_from_incident_plan,
    write_agent_artifact,
)
from lifeline.export import export_plan, seal_digest
from lifeline.incidents import IncidentStore

REPO = Path(__file__).resolve().parent.parent
SCENARIO_PATH = REPO / "scenarios" / "flood_v1.json"


def _response(packet):
    citation = packet["citations"][0]["id"]
    return {
        "headline": "Sealed incident briefing",
        "situation_summary": "This is an interpretation of sealed evidence for a human coordinator.",
        "observations": [{"text": "One proposal is present in the sealed plan.", "citations": [citation]}],
        "questions_for_human": [{"question": "What should be verified next?", "citations": [citation]}],
        "authority_boundary": AUTHORITY_BOUNDARY,
    }


def test_agent_packet_is_derived_only_from_verified_sealed_artifacts(tmp_path):
    export_plan(SCENARIO_PATH, tmp_path, reference_time="2026-07-17T11:00:00Z")
    inputs = load_verified_inputs(tmp_path)
    packet = briefing_packet(inputs)

    assert packet["authority_boundary"] == AUTHORITY_BOUNDARY
    assert packet["plan_sha256"] == inputs.plan_sha256
    assert packet["verification_sha256"] == inputs.verification_sha256
    assert packet["citations"]
    assert all("token" not in json.dumps(item).lower() for item in packet["citations"])
    assert "approvals.jsonl" not in json.dumps(packet).lower()


def test_agent_refuses_unsealed_or_semantically_invalid_inputs(tmp_path):
    export_plan(SCENARIO_PATH, tmp_path)
    plan = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    plan["proposals"][0]["status"] = "DISPATCH_NOW"
    (tmp_path / "plan.json").write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(AgentBriefingError, match="does not match"):
        load_verified_inputs(tmp_path)


def test_agent_response_rejects_unknown_citation_and_authority_drift(tmp_path):
    export_plan(SCENARIO_PATH, tmp_path)
    packet = briefing_packet(load_verified_inputs(tmp_path))
    response = _response(packet)
    response["observations"][0]["citations"] = ["outside:packet"]
    with pytest.raises(AgentBriefingError, match="outside the sealed packet"):
        validate_narration(response, packet)

    response = _response(packet)
    response["authority_boundary"] = "DISPATCH_AUTHORITY"
    with pytest.raises(AgentBriefingError, match="interpretive-only"):
        validate_narration(response, packet)


def test_openai_request_is_structured_no_tools_and_no_retention(tmp_path):
    export_plan(SCENARIO_PATH, tmp_path)
    packet = briefing_packet(load_verified_inputs(tmp_path))
    request = openai_request_body(packet, "gpt-5")

    assert request["store"] is False
    assert "tools" not in request
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["strict"] is True
    assert AUTHORITY_BOUNDARY in request["instructions"]


def test_openai_narration_validates_response_before_writing(tmp_path):
    export_plan(SCENARIO_PATH, tmp_path)
    inputs = load_verified_inputs(tmp_path)
    packet = briefing_packet(inputs)

    def sender(_request):
        return json.dumps({"output_text": json.dumps(_response(packet))}).encode("utf-8")

    narration = openai_narrate(packet, model="gpt-5", api_key="test-secret", request_sender=sender)
    artifact = agent_artifact(inputs, packet, narration, model="gpt-5")
    seal = write_agent_artifact(tmp_path, artifact)

    stored = json.loads((tmp_path / "agent_briefing.json").read_text(encoding="utf-8"))
    assert seal["sha256"] == seal_digest(stored)
    assert stored["authority_boundary"] == AUTHORITY_BOUNDARY
    assert stored["narration"]["observations"][0]["citations"] == [packet["citations"][0]["id"]]
    verify_agent_artifact(stored, inputs)


def test_cli_path_requires_a_key_without_writing_an_agent_artifact(tmp_path, monkeypatch):
    export_plan(SCENARIO_PATH, tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(AgentBriefingError, match="OPENAI_API_KEY"):
        narrate_export(tmp_path, model="gpt-5")
    assert not (tmp_path / "agent_briefing.json").exists()


def test_verify_rejects_a_resigned_agent_artifact_that_claims_authority(tmp_path):
    export_plan(SCENARIO_PATH, tmp_path)
    inputs = load_verified_inputs(tmp_path)
    packet = briefing_packet(inputs)
    artifact = agent_artifact(inputs, packet, _response(packet), model="gpt-5")
    artifact["authority_boundary"] = "DISPATCH_AUTHORITY"
    write_agent_artifact(tmp_path, artifact)

    result = subprocess.run(
        [sys.executable, "-m", "lifeline", "verify", "--out", str(tmp_path)],
        cwd=REPO, capture_output=True, text=True,
    )

    assert result.returncode == 1
    assert "agent briefing seal: FAIL (agent briefing does not preserve the interpretive-only authority boundary)" in result.stdout


def test_verify_rejects_a_resigned_agent_artifact_with_an_outside_citation(tmp_path):
    export_plan(SCENARIO_PATH, tmp_path)
    inputs = load_verified_inputs(tmp_path)
    packet = briefing_packet(inputs)
    artifact = agent_artifact(inputs, packet, _response(packet), model="gpt-5")
    artifact["narration"]["questions_for_human"][0]["citations"] = ["private:mutable-incident"]
    write_agent_artifact(tmp_path, artifact)

    result = subprocess.run(
        [sys.executable, "-m", "lifeline", "verify", "--out", str(tmp_path)],
        cwd=REPO, capture_output=True, text=True,
    )

    assert result.returncode == 1
    assert "agent briefing seal: FAIL (agent response cites evidence outside the sealed packet" in result.stdout


def test_narrate_cli_refuses_without_a_key(tmp_path):
    export_plan(SCENARIO_PATH, tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "lifeline", "narrate", "--out", str(tmp_path)],
        cwd=REPO, capture_output=True, text=True,
        env={"PATH": __import__("os").environ["PATH"]},
    )

    assert result.returncode == 2
    assert "agent narration refused: OPENAI_API_KEY is required" in result.stderr
    assert not (tmp_path / "agent_briefing.json").exists()


def test_incident_plan_uses_the_same_verified_agent_input_boundary(tmp_path, monkeypatch):
    scenario = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    store = IncidentStore(tmp_path / "incidents.sqlite3")
    snapshot = store.create(scenario)
    result = store.plan(snapshot.incident_id, "2026-07-17T11:00:00Z")
    inputs = verified_inputs_from_incident_plan(result)
    packet = briefing_packet(inputs)

    monkeypatch.setattr("lifeline.agent.openai_narrate", lambda given, *, model: _response(given))
    artifact, seal = narrate_incident_plan(result, model="gpt-5")

    assert artifact["plan_sha256"] == result["seal"]["sha256"]
    assert artifact["verification_sha256"] == result["verification_seal"]["sha256"]
    assert seal["sha256"] == seal_digest(artifact)
    verify_agent_artifact(artifact, inputs)
    assert packet["citations"]
