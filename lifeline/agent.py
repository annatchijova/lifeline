"""Optional, read-only OpenAI narration over already-sealed LIFELINE artifacts.

This module is deliberately *outside* the planning and approval paths.  It can
turn a verified plan and verification graph into a cited briefing for a human,
but it has no tools for incident mutation, planning, approval, alert delivery,
or dispatch.  Its output is a separate, non-authoritative artifact bound by
hash to the exact inputs it was allowed to read.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from lifeline.export import CanonicalizationError, _atomic_write_text, seal_digest
from lifeline.verification import VerificationError, verify_payload

AGENT_BRIEFING_VERSION = 1
AGENT_SEAL_VERSION = 1
AUTHORITY_BOUNDARY = "INTERPRETIVE_ONLY"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


class AgentBriefingError(ValueError):
    """The optional narration path cannot safely produce a briefing."""


@dataclass(frozen=True)
class AgentInputs:
    """Verified, sealed inputs permitted to reach the narration provider."""

    plan: dict
    verification: dict
    plan_sha256: str
    verification_sha256: str


SYSTEM_INSTRUCTIONS = """You are LIFELINE Agent Briefing Mode.

Your sole job is to help a human coordinator understand already-sealed,
deterministic LIFELINE artifacts. You are not a planner, dispatcher, approver,
or source of operational facts.

Use only the supplied packet. Do not invent, upgrade, reconcile, or omit
evidence. Do not rank people, recommend a dispatch, choose a resource, issue
instructions, or state that a human should approve or reject a proposal. Keep
contradictions and unresolved evidence explicit. Every factual observation and
every question must cite one or more supplied citation IDs. Return only JSON
matching the requested schema. The authority_boundary value must be exactly
INTERPRETIVE_ONLY."""


NARRATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["headline", "situation_summary", "observations", "questions_for_human", "authority_boundary"],
    "properties": {
        "headline": {"type": "string", "minLength": 1, "maxLength": 280},
        "situation_summary": {"type": "string", "minLength": 1, "maxLength": 2400},
        "observations": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "citations"],
                "properties": {
                    "text": {"type": "string", "minLength": 1, "maxLength": 1200},
                    "citations": {
                        "type": "array", "minItems": 1, "maxItems": 8,
                        "items": {"type": "string", "minLength": 1, "maxLength": 180},
                    },
                },
            },
        },
        "questions_for_human": {
            "type": "array",
            "maxItems": 10,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["question", "citations"],
                "properties": {
                    "question": {"type": "string", "minLength": 1, "maxLength": 700},
                    "citations": {
                        "type": "array", "minItems": 1, "maxItems": 8,
                        "items": {"type": "string", "minLength": 1, "maxLength": 180},
                    },
                },
            },
        },
        "authority_boundary": {"type": "string", "enum": [AUTHORITY_BOUNDARY]},
    },
}


def _read_json_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AgentBriefingError(f"{path.name} is unreadable") from error
    if not isinstance(value, dict):
        raise AgentBriefingError(f"{path.name} must be a JSON object")
    return value


def load_verified_inputs(out_dir: str | Path) -> AgentInputs:
    """Load only artifacts whose seals and verification semantics hold."""
    out = Path(out_dir)
    plan = _read_json_object(out / "plan.json")
    plan_seal = _read_json_object(out / "plan.seal.json")
    verification = _read_json_object(out / "verification.json")
    verification_seal = _read_json_object(out / "verification.seal.json")
    try:
        plan_sha256 = seal_digest(plan)
        verification_sha256 = seal_digest(verification)
    except CanonicalizationError as error:
        raise AgentBriefingError("sealed inputs contain an unsupported value") from error
    if plan_sha256 != plan_seal.get("sha256"):
        raise AgentBriefingError("plan.json does not match plan.seal.json")
    if verification_sha256 != verification_seal.get("sha256"):
        raise AgentBriefingError("verification.json does not match verification.seal.json")
    if verification.get("plan_sha256") != plan_sha256 or verification_seal.get("plan_sha256") != plan_sha256:
        raise AgentBriefingError("verification artifact is not bound to this plan")
    try:
        verify_payload(verification, plan, expected_plan_sha256=plan_sha256)
    except VerificationError as error:
        raise AgentBriefingError(f"verification semantics failed: {error}") from error
    return AgentInputs(plan, verification, plan_sha256, verification_sha256)


def briefing_packet(inputs: AgentInputs) -> dict:
    """Return the small, closed input packet and stable citation vocabulary.

    The packet intentionally does not include approval ledgers, operator tokens,
    incident write endpoints, or raw mutable incident state. A model sees the
    same completed read model a human sees, never authority-bearing controls.
    """
    citations: list[dict] = []
    proposals: list[dict] = []
    for proposal in inputs.plan.get("proposals", []):
        if not isinstance(proposal, dict):
            continue
        request_id = proposal.get("request_id")
        if not isinstance(request_id, str):
            continue
        citation_id = f"proposal:{request_id}"
        citations.append({
            "id": citation_id,
            "kind": "proposal",
            "request_id": request_id,
            "status": proposal.get("status"),
            "reasons": proposal.get("reasons", []),
            "resource_id": proposal.get("resource_id"),
            "shelter_id": proposal.get("shelter_id"),
            "eta_minutes": proposal.get("eta_minutes"),
        })
        proposals.append({
            "citation_id": citation_id,
            "request_id": request_id,
            "status": proposal.get("status"),
            "reasons": proposal.get("reasons", []),
        })

    nodes: list[dict] = []
    for index, node in enumerate(inputs.verification.get("nodes", [])):
        if not isinstance(node, dict) or not isinstance(node.get("request_id"), str):
            continue
        citation_id = f"verification:{node['request_id']}:{index}"
        summary = {
            "id": citation_id,
            "kind": "verification_node",
            "request_id": node["request_id"],
            "proposal_status": node.get("proposal_status"),
            "disposition": node.get("disposition"),
            "reason_code": node.get("reason_code"),
            "detail": node.get("detail"),
            "action_required": node.get("action_required"),
            "required_artifacts": node.get("required_artifacts", []),
            "supports": node.get("supports", []),
            "refutes": node.get("refutes", []),
            "unresolved": node.get("unresolved", []),
        }
        citations.append(summary)
        nodes.append({"citation_id": citation_id, **{key: value for key, value in summary.items() if key != "id"}})

    findings = inputs.plan.get("validation_findings", [])
    safe_findings = [finding for finding in findings if isinstance(finding, dict)]
    for index, finding in enumerate(safe_findings):
        entity_type = finding.get("entity_type")
        entity_id = finding.get("entity_id")
        if not isinstance(entity_type, str) or not isinstance(entity_id, str):
            continue
        citations.append({"id": f"finding:{entity_type}:{entity_id}:{index}", "kind": "validation_finding", **finding})

    return {
        "packet_version": 1,
        "authority_boundary": AUTHORITY_BOUNDARY,
        "plan_sha256": inputs.plan_sha256,
        "verification_sha256": inputs.verification_sha256,
        "briefing": inputs.plan.get("briefing", {}),
        "proposals": proposals,
        "verification_nodes": nodes,
        "validation_findings": safe_findings,
        "citations": citations,
        "limitations": [
            "This packet contains completed, sealed read models only.",
            "The narrator cannot create, change, approve, reject, or dispatch an operational action.",
            "A citation identifies supplied evidence; it does not turn a model statement into operational truth.",
        ],
    }


def _require_string(value: object, field: str, *, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise AgentBriefingError(f"agent response has an invalid {field}")
    return value


def _validate_cited_items(value: object, field: str, known_citations: set[str], text_key: str, *, limit: int) -> list[dict]:
    if not isinstance(value, list) or len(value) > limit:
        raise AgentBriefingError(f"agent response has an invalid {field}")
    items: list[dict] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != {text_key, "citations"}:
            raise AgentBriefingError(f"agent response has an invalid {field}[{index}]")
        text = _require_string(item.get(text_key), f"{field}[{index}].{text_key}", limit=1200)
        refs = item.get("citations")
        if not isinstance(refs, list) or not refs or len(refs) > 8 or any(not isinstance(ref, str) for ref in refs):
            raise AgentBriefingError(f"agent response has invalid citations in {field}[{index}]")
        if len(set(refs)) != len(refs) or any(ref not in known_citations for ref in refs):
            raise AgentBriefingError(f"agent response cites evidence outside the sealed packet in {field}[{index}]")
        items.append({text_key: text, "citations": refs})
    return items


def validate_narration(response: object, packet: dict) -> dict:
    """Reject output that is not a cited, explicitly non-authoritative brief."""
    if not isinstance(response, dict) or set(response) != {
        "headline", "situation_summary", "observations", "questions_for_human", "authority_boundary",
    }:
        raise AgentBriefingError("agent response does not match the narration contract")
    if response.get("authority_boundary") != AUTHORITY_BOUNDARY:
        raise AgentBriefingError("agent response does not preserve the interpretive-only authority boundary")
    citation_rows = packet.get("citations")
    if not isinstance(citation_rows, list):
        raise AgentBriefingError("sealed packet has no citation vocabulary")
    known = {item.get("id") for item in citation_rows if isinstance(item, dict) and isinstance(item.get("id"), str)}
    if not known:
        raise AgentBriefingError("sealed packet has an empty citation vocabulary")
    return {
        "headline": _require_string(response.get("headline"), "headline", limit=280),
        "situation_summary": _require_string(response.get("situation_summary"), "situation_summary", limit=2400),
        "observations": _validate_cited_items(response.get("observations"), "observations", known, "text", limit=12),
        "questions_for_human": _validate_cited_items(response.get("questions_for_human"), "questions_for_human", known, "question", limit=10),
        "authority_boundary": AUTHORITY_BOUNDARY,
    }


def openai_request_body(packet: dict, model: str) -> dict:
    """Build a no-tools Responses request that sets ``store`` to false."""
    if not isinstance(model, str) or not model.strip() or len(model) > 128:
        raise AgentBriefingError("model must be a non-empty short string")
    return {
        "model": model,
        "store": False,
        "instructions": SYSTEM_INSTRUCTIONS,
        "input": [{
            "role": "user",
            "content": [{
                "type": "input_text",
                "text": "Create an interpretive briefing from this sealed LIFELINE packet:\n" + json.dumps(
                    packet, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
            }],
        }],
        "text": {"format": {
            "type": "json_schema",
            "name": "lifeline_agent_briefing",
            "strict": True,
            "schema": NARRATION_SCHEMA,
        }},
    }


def _response_output_text(response: object) -> str:
    if not isinstance(response, dict):
        raise AgentBriefingError("OpenAI response is not a JSON object")
    direct = response.get("output_text")
    if isinstance(direct, str) and direct:
        return direct
    output = response.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if isinstance(content, dict) and content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    return content["text"]
    raise AgentBriefingError("OpenAI response did not contain output text")


def openai_narrate(
    packet: dict,
    *,
    model: str,
    api_key: str | None = None,
    request_sender: Callable[[Request], bytes] | None = None,
) -> dict:
    """Call OpenAI only after all deterministic input checks have completed."""
    secret = api_key or os.environ.get("OPENAI_API_KEY")
    if not secret:
        raise AgentBriefingError("OPENAI_API_KEY is required for optional agent narration")
    request = Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(openai_request_body(packet, model), separators=(",", ":"), ensure_ascii=True).encode("utf-8"),
        headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        if request_sender is not None:
            raw = request_sender(request)
        else:
            with urlopen(request, timeout=45) as response:
                raw = response.read()
        response = json.loads(raw.decode("utf-8"))
    except HTTPError as error:
        raise AgentBriefingError(f"OpenAI narration request failed with HTTP {error.code}") from error
    except (URLError, TimeoutError) as error:
        raise AgentBriefingError("OpenAI narration request could not be completed") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AgentBriefingError("OpenAI narration response was unreadable") from error
    try:
        narration = json.loads(_response_output_text(response))
    except json.JSONDecodeError as error:
        raise AgentBriefingError("OpenAI narration was not valid JSON") from error
    return validate_narration(narration, packet)


def agent_artifact(inputs: AgentInputs, packet: dict, narration: dict, *, model: str) -> dict:
    """Bind a validated interpretation to the exact sealed inputs it read."""
    return {
        "agent_briefing_version": AGENT_BRIEFING_VERSION,
        "authority_boundary": AUTHORITY_BOUNDARY,
        "provider": "openai_responses",
        "model": model,
        "plan_sha256": inputs.plan_sha256,
        "verification_sha256": inputs.verification_sha256,
        "packet_sha256": seal_digest(packet),
        "narration": narration,
        "limitations": [
            "This is an optional interpretation layer, not a planning or approval artifact.",
            "The agent received no mutation, approval, dispatch, or external-alert tool.",
            "Only the cited sealed packet was supplied to the provider.",
        ],
    }


def verify_agent_artifact(artifact: object, inputs: AgentInputs) -> None:
    """Check that a narration remains bound to the artifacts it was allowed to read.

    This verifies integrity, input binding, the citation vocabulary, and the
    non-authority contract. It intentionally cannot prove that an LLM's prose
    was true or useful; those are not cryptographic properties.
    """
    if not isinstance(artifact, dict) or set(artifact) != {
        "agent_briefing_version", "authority_boundary", "provider", "model",
        "plan_sha256", "verification_sha256", "packet_sha256", "narration", "limitations",
    }:
        raise AgentBriefingError("agent briefing does not match the artifact contract")
    if artifact.get("agent_briefing_version") != AGENT_BRIEFING_VERSION:
        raise AgentBriefingError("agent briefing has an unsupported version")
    if artifact.get("authority_boundary") != AUTHORITY_BOUNDARY:
        raise AgentBriefingError("agent briefing does not preserve the interpretive-only authority boundary")
    if artifact.get("provider") != "openai_responses" or not isinstance(artifact.get("model"), str):
        raise AgentBriefingError("agent briefing has an unsupported provider or model")
    if artifact.get("plan_sha256") != inputs.plan_sha256 or artifact.get("verification_sha256") != inputs.verification_sha256:
        raise AgentBriefingError("agent briefing is not bound to the current sealed inputs")
    packet = briefing_packet(inputs)
    if artifact.get("packet_sha256") != seal_digest(packet):
        raise AgentBriefingError("agent briefing packet binding does not match the sealed inputs")
    validate_narration(artifact.get("narration"), packet)
    limitations = artifact.get("limitations")
    if not isinstance(limitations, list) or not all(isinstance(item, str) for item in limitations):
        raise AgentBriefingError("agent briefing has invalid limitations")


def write_agent_artifact(out_dir: str | Path, artifact: dict) -> dict:
    """Atomically publish a separately sealed, non-authoritative narration."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    digest = seal_digest(artifact)
    _atomic_write_text(out / "agent_briefing.json", json.dumps(artifact, sort_keys=True, indent=2, ensure_ascii=True) + "\n")
    seal = {
        "sha256": digest,
        "agent_briefing_version": AGENT_BRIEFING_VERSION,
        "seal_version": AGENT_SEAL_VERSION,
        "plan_sha256": artifact["plan_sha256"],
        "verification_sha256": artifact["verification_sha256"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_write_text(out / "agent_briefing.seal.json", json.dumps(seal, sort_keys=True, indent=2, ensure_ascii=True) + "\n")
    return seal


def narrate_export(out_dir: str | Path, *, model: str) -> tuple[dict, dict]:
    """Create and write an OpenAI narration from verified local artifacts."""
    inputs = load_verified_inputs(out_dir)
    packet = briefing_packet(inputs)
    narration = openai_narrate(packet, model=model)
    artifact = agent_artifact(inputs, packet, narration, model=model)
    return artifact, write_agent_artifact(out_dir, artifact)
