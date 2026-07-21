"""Optional, read-only provider-assisted reading guides over sealed artifacts.

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
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from lifeline.export import CANONICALIZE_VERSION, CanonicalizationError, _atomic_write_text, seal_digest
from lifeline.verification import VerificationError, verify_payload

AGENT_BRIEFING_VERSION = 5
AGENT_SEAL_VERSION = 3
AUTHORITY_BOUNDARY = "INTERPRETIVE_ONLY"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
NVIDIA_CHAT_COMPLETIONS_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

# OpenAI remains the public/default hackathon integration.  NVIDIA is a local
# development adapter for exercising the same closed reading-guide contract
# when an OpenAI key is unavailable.  The sealed artifact records which one
# actually supplied the citation selection.
_PROVIDER_ARTIFACT_IDS = {
    "openai": "openai_responses",
    "nvidia": "nvidia_chat_completions",
}
_SUPPORTED_ARTIFACT_PROVIDERS = frozenset(_PROVIDER_ARTIFACT_IDS.values())


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
instructions, or state that a human should approve or reject a proposal.

You do not return prose. Return only opaque citation IDs for a non-authoritative
reading guide. LIFELINE renders every displayed sentence locally from sealed
facts and fixed templates. Select citations only; never return a label,
explanation, recommendation, or instruction. The authority_boundary value must
be exactly INTERPRETIVE_ONLY."""


GUIDE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "focus_citations", "question_citations", "authority_boundary",
    ],
    "properties": {
        "focus_citations": {
            "type": "array", "minItems": 1, "maxItems": 12,
            "items": {"type": "string", "minLength": 1, "maxLength": 180},
        },
        "question_citations": {
            "type": "array", "maxItems": 10,
            "items": {"type": "string", "minLength": 1, "maxLength": 180},
        },
        "authority_boundary": {"type": "string", "enum": [AUTHORITY_BOUNDARY]},
    },
}

_EVENT_TYPES = frozenset({"incident_created", "report_added", "report_superseded"})
# The provider packet never carries reporter-controlled strings (identifiers,
# zones, labels, provenance, timestamps, or free-text validator details).
# These fields retain enough typed operational context for narration while the
# local UI resolves opaque citations to their real sealed evidence.
_REPORT_FIELDS = {
    "request": ("people", "urgency", "medical_need", "verification_state", "freshness"),
    "resource": ("capacity", "available", "can_transport_medical", "verification_state", "freshness"),
    "shelter": ("beds_open", "open", "verification_state", "freshness"),
    "route": ("eta_minutes", "open", "verification_state", "freshness"),
}
_REPORT_INT_FIELDS = frozenset({"people", "urgency", "capacity", "beds_open", "eta_minutes"})
_REPORT_BOOL_FIELDS = frozenset({"medical_need", "available", "can_transport_medical", "open"})
_REPORT_ENUM_FIELDS = {
    "verification_state": frozenset({"verified", "unverified", "conflicting"}),
    "freshness": frozenset({"high", "medium", "low"}),
}
_PROPOSAL_REASON_CODES = {
    "no eligible available resource": "NO_ELIGIBLE_RESOURCE",
    "no reachable destination shelter capacity": "NO_DESTINATION_CAPACITY",
    "human approval required": "HUMAN_APPROVAL_REQUIRED",
    "unverified report": "UNVERIFIED_REPORT",
    "conflicting reports": "CONFLICTING_REPORTS",
    "stale report": "STALE_REPORT",
}
_VERIFICATION_REASON_CODES = frozenset({
    "ACCESS_ROUTE_CONTRADICTION", "ACCESS_ROUTE_EVIDENCE_UNUSABLE", "EVIDENCE_GATES_CLEAR",
    "FEASIBILITY_NOT_ESTABLISHED", "REQUEST_CONTRADICTION", "REQUEST_STALE", "REQUEST_UNVERIFIED",
    "RESOURCE_EVIDENCE_UNUSABLE", "ROUTE_CONTRADICTION", "ROUTE_EVIDENCE_UNUSABLE",
    "SHELTER_EVIDENCE_UNUSABLE",
})
_VERIFICATION_ACTIONS = frozenset({
    "HUMAN_APPROVAL_REQUIRED", "VERIFY_REQUEST_REPORT", "OBTAIN_DISCRIMINATING_EVIDENCE",
    "OBTAIN_FRESH_REQUEST_REPORT", "HUMAN_REVIEW_OF_FEASIBILITY",
    "OBTAIN_DISCRIMINATING_ROUTE_EVIDENCE", "VERIFY_CURRENT_ROUTE_STATUS",
    "OBTAIN_DISCRIMINATING_ACCESS_ROUTE_EVIDENCE", "VERIFY_CURRENT_ACCESS_ROUTE_STATUS",
    "VERIFY_CURRENT_RESOURCE_AVAILABILITY", "VERIFY_CURRENT_DESTINATION_CAPACITY",
})
_EVIDENCE_ASSERTIONS = frozenset({
    "access_route_reported_closed", "access_route_reported_open", "resource_reported_available",
    "route_reported_closed", "route_reported_open", "shelter_reported_capacity_available",
})
_VALIDATION_CODES = frozenset({
    "FUTURE_TIMESTAMP", "POSSIBLE_DUPLICATE", "ROUTE_CONTRADICTION", "STALE_REPORT",
    "STALENESS_UNCHECKED", "UNPARSEABLE_TIMESTAMP",
})
_ENTITY_TYPES = frozenset({"incident", "scenario", "request", "resource", "shelter", "route"})


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
    return verified_inputs_from_payload(plan, plan_seal, verification, verification_seal)


def verified_inputs_from_payload(plan: object, plan_seal: object, verification: object, verification_seal: object) -> AgentInputs:
    """Validate a plan/verification quartet already held in memory.

    The local incident API creates the same quartet from a hash-linked incident
    revision. Keeping this check here means its agent path has the exact same
    evidence gate as the standalone export path.
    """
    if not all(isinstance(value, dict) for value in (plan, plan_seal, verification, verification_seal)):
        raise AgentBriefingError("sealed inputs must be JSON objects")
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


def verified_inputs_from_incident_plan(result: object) -> AgentInputs:
    """Extract the sealed quartet returned by ``IncidentStore.plan``."""
    if not isinstance(result, dict):
        raise AgentBriefingError("incident plan result must be a JSON object")
    return verified_inputs_from_payload(
        result.get("plan"), result.get("seal"), result.get("verification"), result.get("verification_seal"))


def _report_read_model(entity_type: str, report: object) -> dict:
    """Keep event narration on an allowlisted, non-textual read model."""
    if not isinstance(report, dict) or entity_type not in _REPORT_FIELDS:
        return {}
    safe: dict[str, object] = {}
    for field in _REPORT_FIELDS[entity_type]:
        if field not in report:
            continue
        value = report[field]
        if _safe_change_value(field, value):
            safe[field] = value
    return safe


def incident_change_read_model(events: Iterable[object], inputs: AgentInputs) -> list[dict]:
    """Turn verified ledger events into a small, cited change read model.

    This does not forward raw event payloads (whose free-text fields may be
    untrusted) to the model. It forwards an allowlisted summary of what changed
    together with the immutable event hash that a coordinator can inspect.
    ``IncidentStore.events`` verifies the chain before returning these rows;
    this function additionally checks the shape and revision bounds.
    """
    incident_revision = inputs.plan.get("incident_revision")
    if incident_revision is not None and (not isinstance(incident_revision, int) or incident_revision < 1):
        raise AgentBriefingError("sealed incident plan has an invalid revision")
    summaries: list[dict] = []
    revisions: set[int] = set()
    for raw in events:
        if not isinstance(raw, dict):
            raise AgentBriefingError("incident change event must be an object")
        revision = raw.get("revision")
        event_type = raw.get("event_type")
        entity_type = raw.get("entity_type")
        entity_id = raw.get("entity_id")
        event_hash = raw.get("event_hash")
        submitted_at = raw.get("submitted_at")
        if (
            not isinstance(revision, int) or revision < 1 or revision in revisions
            or not isinstance(event_type, str) or event_type not in _EVENT_TYPES
            or not isinstance(entity_type, str) or entity_type not in _ENTITY_TYPES or not isinstance(entity_id, str)
            or not isinstance(event_hash, str) or len(event_hash) != 64
            or any(char not in "0123456789abcdef" for char in event_hash)
            or not isinstance(submitted_at, str)
            or incident_revision is not None and revision > incident_revision
        ):
            raise AgentBriefingError("incident change event has an invalid shape")
        revisions.add(revision)
        payload = raw.get("payload")
        summary = {
            "citation_id": f"event:{revision}:{event_hash}",
            "revision": revision,
            "event_type": event_type,
            "entity_type": entity_type,
            "event_hash": event_hash,
        }
        if event_type == "report_added":
            summary["current_report"] = _report_read_model(entity_type, payload)
        elif event_type == "report_superseded":
            if not isinstance(payload, dict):
                raise AgentBriefingError("superseded event has an invalid payload")
            previous = _report_read_model(entity_type, payload.get("previous"))
            replacement = _report_read_model(entity_type, payload.get("replacement"))
            changes = [
                {"field": field, "before": previous.get(field), "after": replacement.get(field)}
                for field in _REPORT_FIELDS.get(entity_type, ())
                if previous.get(field) != replacement.get(field)
            ]
            summary["changes"] = changes
            summary["current_report"] = replacement
        summaries.append(summary)
    return _validated_incident_changes(summaries, inputs)


def _safe_change_value(field: str, value: object, *, allow_none: bool = False) -> bool:
    """Allow only closed enums and non-textual values into the provider packet."""
    if value is None:
        return allow_none
    if field in _REPORT_INT_FIELDS:
        return isinstance(value, int) and not isinstance(value, bool)
    if field in _REPORT_BOOL_FIELDS:
        return isinstance(value, bool)
    if field in _REPORT_ENUM_FIELDS:
        return isinstance(value, str) and value in _REPORT_ENUM_FIELDS[field]
    return False


def _validated_incident_changes(changes: object, inputs: AgentInputs) -> list[dict]:
    """Validate the portable, allowlisted event read model stored in an artifact."""
    if not isinstance(changes, list) or len(changes) > 64:
        raise AgentBriefingError("incident change read model is invalid")
    incident_revision = inputs.plan.get("incident_revision")
    if incident_revision is not None and (not isinstance(incident_revision, int) or incident_revision < 1):
        raise AgentBriefingError("sealed incident plan has an invalid revision")
    normalized: list[dict] = []
    revisions: set[int] = set()
    for change in changes:
        if not isinstance(change, dict):
            raise AgentBriefingError("incident change read model is invalid")
        base = {"citation_id", "revision", "event_type", "entity_type", "event_hash"}
        event_type = change.get("event_type")
        entity_type = change.get("entity_type")
        expected = base
        if event_type == "report_added":
            expected = base | {"current_report"}
        elif event_type == "report_superseded":
            expected = base | {"current_report", "changes"}
        elif event_type != "incident_created":
            raise AgentBriefingError("incident change read model is invalid")
        if set(change) != expected:
            raise AgentBriefingError("incident change read model is invalid")
        revision = change.get("revision")
        event_hash = change.get("event_hash")
        citation_id = change.get("citation_id")
        if (
            not isinstance(revision, int) or revision < 1 or revision in revisions
            or incident_revision is not None and revision > incident_revision
            or not isinstance(event_hash, str) or len(event_hash) != 64
            or any(char not in "0123456789abcdef" for char in event_hash)
            or citation_id != f"event:{revision}:{event_hash}"
            or not isinstance(entity_type, str) or entity_type not in _ENTITY_TYPES
        ):
            raise AgentBriefingError("incident change read model is invalid")
        revisions.add(revision)
        item = {key: change[key] for key in base}
        if event_type in {"report_added", "report_superseded"}:
            allowed_fields = _REPORT_FIELDS.get(entity_type)
            report = change.get("current_report")
            if allowed_fields is None or not isinstance(report, dict) or not set(report) <= set(allowed_fields):
                raise AgentBriefingError("incident change read model is invalid")
            if any(not _safe_change_value(field, value) for field, value in report.items()):
                raise AgentBriefingError("incident change read model is invalid")
            item["current_report"] = {field: report[field] for field in allowed_fields if field in report}
        if event_type == "report_superseded":
            raw_changes = change.get("changes")
            allowed_fields = set(_REPORT_FIELDS[entity_type])
            if not isinstance(raw_changes, list) or len(raw_changes) > len(allowed_fields):
                raise AgentBriefingError("incident change read model is invalid")
            fields: set[str] = set()
            normalized_changes = []
            for delta in raw_changes:
                if not isinstance(delta, dict) or set(delta) != {"field", "before", "after"}:
                    raise AgentBriefingError("incident change read model is invalid")
                field = delta.get("field")
                if not isinstance(field, str) or field not in allowed_fields or field in fields:
                    raise AgentBriefingError("incident change read model is invalid")
                if not _safe_change_value(field, delta.get("before"), allow_none=True) or not _safe_change_value(field, delta.get("after"), allow_none=True):
                    raise AgentBriefingError("incident change read model is invalid")
                fields.add(field)
                normalized_changes.append({"field": field, "before": delta.get("before"), "after": delta.get("after")})
            item["changes"] = normalized_changes
        normalized.append(item)
    return sorted(normalized, key=lambda item: item["revision"])


def briefing_packet(
    inputs: AgentInputs,
    *,
    incident_events: Iterable[object] = (),
    incident_changes: object | None = None,
) -> dict:
    """Return the small, closed input packet and stable citation vocabulary.

    The packet intentionally does not include approval ledgers, operator tokens,
    incident write endpoints, raw mutable incident state, or reporter-supplied
    strings. A model sees opaque citation references and typed operational
    state; the local UI resolves those references for the human coordinator.
    """
    citations: list[dict] = []
    proposals: list[dict] = []
    proposal_refs: dict[str, str] = {}
    for index, proposal in enumerate(inputs.plan.get("proposals", [])):
        if not isinstance(proposal, dict):
            raise AgentBriefingError("sealed plan has an invalid proposal")
        request_id = proposal.get("request_id")
        status = proposal.get("status")
        if not isinstance(request_id, str) or request_id in proposal_refs or status not in {"PROPOSED", "NEEDS_HUMAN_REVIEW"}:
            raise AgentBriefingError("sealed plan has an invalid proposal")
        citation_id = f"proposal:{index}"
        proposal_refs[request_id] = citation_id
        metrics: dict[str, int] = {}
        reason_codes: list[str] = []
        reasons = proposal.get("reasons")
        if not isinstance(reasons, list):
            raise AgentBriefingError("sealed plan has invalid proposal reasons")
        for reason in reasons:
            if not isinstance(reason, str):
                raise AgentBriefingError("sealed plan has invalid proposal reasons")
            if reason in _PROPOSAL_REASON_CODES:
                reason_codes.append(_PROPOSAL_REASON_CODES[reason])
                continue
            for field in ("urgency", "people", "eta_minutes"):
                prefix = field + "="
                number = reason[len(prefix):] if reason.startswith(prefix) else ""
                if number and number.isascii() and number.isdecimal():
                    metrics[field] = int(number)
                    break
        summary = {
            "citation_id": citation_id,
            "proposal_number": index + 1,
            "status": status,
            "metrics": metrics,
            "reason_codes": sorted(set(reason_codes)),
        }
        citations.append({"id": citation_id, "kind": "proposal", **{key: value for key, value in summary.items() if key != "citation_id"}})
        proposals.append(summary)

    nodes: list[dict] = []
    for index, node in enumerate(inputs.verification.get("nodes", [])):
        if not isinstance(node, dict) or not isinstance(node.get("request_id"), str):
            raise AgentBriefingError("sealed verification artifact has an invalid node")
        proposal_citation = proposal_refs.get(node["request_id"])
        if proposal_citation is None:
            raise AgentBriefingError("sealed verification node has no proposal reference")
        reason_code = node.get("reason_code")
        action = node.get("action_required")
        if reason_code not in _VERIFICATION_REASON_CODES or action not in _VERIFICATION_ACTIONS:
            raise AgentBriefingError("sealed verification node has unsupported vocabulary")
        citation_id = f"verification:{index}"
        def evidence_read_model(rows: object) -> list[dict]:
            if not isinstance(rows, list):
                raise AgentBriefingError("sealed verification node has invalid evidence")
            safe_rows = []
            for row in rows:
                if not isinstance(row, dict):
                    raise AgentBriefingError("sealed verification node has invalid evidence")
                state = row.get("verification_state")
                freshness = row.get("freshness")
                observation = row.get("observation")
                assertion = row.get("assertion")
                if state not in _REPORT_ENUM_FIELDS["verification_state"] or freshness not in _REPORT_ENUM_FIELDS["freshness"]:
                    raise AgentBriefingError("sealed verification node has unsupported evidence state")
                if observation not in {"ANALYZED", "NOT_ANALYZED", "ANALYSIS_FAILED"}:
                    raise AgentBriefingError("sealed verification node has unsupported observation state")
                item = {"verification_state": state, "freshness": freshness, "observation": observation}
                if assertion is not None:
                    if assertion not in _EVIDENCE_ASSERTIONS:
                        raise AgentBriefingError("sealed verification node has unsupported evidence assertion")
                    item["assertion"] = assertion
                safe_rows.append(item)
            return safe_rows
        summary = {
            "citation_id": citation_id,
            "proposal_citation": proposal_citation,
            "proposal_status": node.get("proposal_status"),
            "disposition": node.get("disposition"),
            "reason_code": reason_code,
            "action_required": action,
            "supports": evidence_read_model(node.get("supports")),
            "refutes": evidence_read_model(node.get("refutes")),
        }
        citations.append({"id": citation_id, "kind": "verification_node", **{key: value for key, value in summary.items() if key != "citation_id"}})
        nodes.append(summary)

    changes = (
        _validated_incident_changes(incident_changes, inputs)
        if incident_changes is not None
        else incident_change_read_model(incident_events, inputs)
    )
    for change in changes:
        citations.append({"id": change["citation_id"], "kind": "incident_event", **{
            key: value for key, value in change.items() if key != "citation_id"
        }})

    findings: list[dict] = []
    for index, finding in enumerate(inputs.plan.get("validation_findings", [])):
        if not isinstance(finding, dict):
            raise AgentBriefingError("sealed plan has an invalid validation finding")
        code = finding.get("code")
        severity = finding.get("severity")
        entity_type = finding.get("entity_type")
        if code not in _VALIDATION_CODES or severity not in {"info", "warn"} or entity_type not in _ENTITY_TYPES:
            raise AgentBriefingError("sealed plan has unsupported validation vocabulary")
        citation_id = f"finding:{index}"
        summary = {"citation_id": citation_id, "code": code, "severity": severity, "entity_type": entity_type}
        findings.append(summary)
        citations.append({"id": citation_id, "kind": "validation_finding", **{key: value for key, value in summary.items() if key != "citation_id"}})

    return {
        "packet_version": 2,
        "authority_boundary": AUTHORITY_BOUNDARY,
        "plan_sha256": inputs.plan_sha256,
        "verification_sha256": inputs.verification_sha256,
        "briefing": {
            "proposal_counts": {
                "proposed": sum(item["status"] == "PROPOSED" for item in proposals),
                "needs_human_review": sum(item["status"] == "NEEDS_HUMAN_REVIEW" for item in proposals),
                "total": len(proposals),
            },
            "validation": {
                "warn": sum(item["severity"] == "warn" for item in findings),
                "info": sum(item["severity"] == "info" for item in findings),
                "by_code": [
                    {"code": code, "count": sum(item["code"] == code for item in findings)}
                    for code in sorted({item["code"] for item in findings})
                ],
            },
        },
        "proposals": proposals,
        "verification_nodes": nodes,
        "incident_changes": changes,
        "validation_findings": findings,
        "citations": citations,
        "limitations": [
            "This packet contains completed, sealed read models only.",
            "The narrator cannot create, change, approve, reject, or dispatch an operational action.",
            "A citation identifies supplied evidence; it does not turn a model statement into operational truth.",
        ],
    }


def _citation_rows(packet: dict) -> tuple[list[dict], dict[str, dict]]:
    rows = packet.get("citations")
    if not isinstance(rows, list):
        raise AgentBriefingError("sealed packet has no citation vocabulary")
    ordered: list[dict] = []
    by_id: dict[str, dict] = {}
    for row in rows:
        citation_id = row.get("id") if isinstance(row, dict) else None
        if not isinstance(citation_id, str) or not citation_id or citation_id in by_id:
            raise AgentBriefingError("sealed packet has an invalid citation vocabulary")
        ordered.append(row)
        by_id[citation_id] = row
    if not ordered:
        raise AgentBriefingError("sealed packet has an empty citation vocabulary")
    return ordered, by_id


def _validate_citation_selection(
    value: object,
    field: str,
    *,
    ordered_ids: list[str],
    known_citations: set[str],
    minimum: int,
    maximum: int,
) -> list[str]:
    if (
        not isinstance(value, list)
        or not minimum <= len(value) <= maximum
        or any(not isinstance(ref, str) for ref in value)
    ):
        raise AgentBriefingError(f"agent response has invalid citations in {field}")
    selected = set(value)
    if len(selected) != len(value) or any(ref not in known_citations for ref in selected):
        raise AgentBriefingError(f"agent response cites evidence outside the sealed packet in {field}")
    # The model is not permitted to turn array position into a priority order.
    return [citation_id for citation_id in ordered_ids if citation_id in selected]


def validate_briefing_guide(response: object, packet: dict) -> dict:
    """Accept only opaque citation selections from the external provider.

    No provider-controlled prose crosses this boundary.  The model may select
    already-sealed evidence for a reading guide, but the human-visible language
    is generated locally by :func:`controlled_narration`.
    """
    if not isinstance(response, dict) or set(response) != {
        "focus_citations", "question_citations", "authority_boundary",
    }:
        raise AgentBriefingError("agent response does not match the reading-guide contract")
    if response.get("authority_boundary") != AUTHORITY_BOUNDARY:
        raise AgentBriefingError("agent response does not preserve the interpretive-only authority boundary")
    rows, by_id = _citation_rows(packet)
    ordered_ids = [row["id"] for row in rows]
    known = set(by_id)
    return {
        "focus_citations": _validate_citation_selection(
            response.get("focus_citations"), "focus_citations", ordered_ids=ordered_ids,
            known_citations=known, minimum=1, maximum=12),
        "question_citations": _validate_citation_selection(
            response.get("question_citations"), "question_citations", ordered_ids=ordered_ids,
            known_citations=known, minimum=0, maximum=10),
        "authority_boundary": AUTHORITY_BOUNDARY,
    }


def _briefing_citations(rows: list[dict], *, maximum: int = 8) -> list[str]:
    preferred = [row["id"] for row in rows if row.get("kind") in {"proposal", "verification_node", "validation_finding"}]
    return (preferred or [row["id"] for row in rows])[:maximum]


def _controlled_observation(row: dict) -> str:
    kind = row.get("kind")
    if kind == "proposal":
        number = row.get("proposal_number")
        status = row.get("status")
        metrics = row.get("metrics")
        if not isinstance(number, int) or status not in {"PROPOSED", "NEEDS_HUMAN_REVIEW"} or not isinstance(metrics, dict):
            raise AgentBriefingError("sealed packet has an invalid proposal citation")
        metric_parts = [
            f"{field}={metrics[field]}"
            for field in ("people", "urgency", "eta_minutes")
            if isinstance(metrics.get(field), int) and not isinstance(metrics.get(field), bool)
        ]
        suffix = f" Sealed metrics: {', '.join(metric_parts)}." if metric_parts else ""
        return f"Sealed proposal {number} has status {status}.{suffix}"
    if kind == "verification_node":
        proposal = row.get("proposal_citation")
        disposition = row.get("disposition")
        reason = row.get("reason_code")
        action = row.get("action_required")
        if not all(isinstance(value, str) and value for value in (proposal, disposition, reason, action)):
            raise AgentBriefingError("sealed packet has an invalid verification citation")
        return (
            f"Verification for {proposal} has disposition {disposition}; "
            f"recorded reason {reason}; recorded human follow-up {action}."
        )
    if kind == "validation_finding":
        code = row.get("code")
        severity = row.get("severity")
        entity_type = row.get("entity_type")
        if not all(isinstance(value, str) and value for value in (code, severity, entity_type)):
            raise AgentBriefingError("sealed packet has an invalid validation citation")
        return f"Validation finding {code} has severity {severity} for a {entity_type} record."
    if kind == "incident_event":
        revision = row.get("revision")
        event_type = row.get("event_type")
        entity_type = row.get("entity_type")
        if not isinstance(revision, int) or not all(isinstance(value, str) and value for value in (event_type, entity_type)):
            raise AgentBriefingError("sealed packet has an invalid incident-event citation")
        return f"Incident revision {revision} recorded {event_type} for a {entity_type} record."
    raise AgentBriefingError("sealed packet has an unsupported citation kind")


def _controlled_question(row: dict) -> str:
    kind = row.get("kind")
    if kind == "verification_node":
        return "What does the cited Verification Graph leave unresolved for human review?"
    if kind == "proposal":
        return "After inspecting the cited sealed evidence, what decision, if any, should an authorized human record?"
    if kind == "validation_finding":
        return "Can a human corroborate or correct the cited validation finding?"
    if kind == "incident_event":
        return "Does the cited incident revision change what evidence a human should inspect?"
    raise AgentBriefingError("sealed packet has an unsupported citation kind")


def controlled_narration(packet: dict, guide: object) -> dict:
    """Render all displayed agent language locally from sealed, typed values.

    The provider supplies only a de-duplicated *set* of opaque citation IDs.
    Its output cannot introduce a recommendation, instruction, person, route,
    or resource identifier into this narration.
    """
    normalized_guide = validate_briefing_guide(guide, packet)
    rows, by_id = _citation_rows(packet)
    briefing = packet.get("briefing")
    proposal_counts = briefing.get("proposal_counts") if isinstance(briefing, dict) else None
    validation = briefing.get("validation") if isinstance(briefing, dict) else None
    if not isinstance(proposal_counts, dict) or not isinstance(validation, dict):
        raise AgentBriefingError("sealed packet has an invalid briefing summary")
    proposed = proposal_counts.get("proposed")
    needs_review = proposal_counts.get("needs_human_review")
    total = proposal_counts.get("total")
    warnings = validation.get("warn")
    info = validation.get("info")
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in (proposed, needs_review, total, warnings, info)):
        raise AgentBriefingError("sealed packet has an invalid briefing summary")
    summary_citations = _briefing_citations(rows)
    observations = [
        {"text": _controlled_observation(by_id[citation_id]), "citations": [citation_id]}
        for citation_id in normalized_guide["focus_citations"]
    ]
    questions = [
        {"question": _controlled_question(by_id[citation_id]), "citations": [citation_id]}
        for citation_id in normalized_guide["question_citations"]
    ]
    return {
        "headline": (
            f"Sealed incident: {proposed} proposal(s) await a human decision; "
            f"{needs_review} require evidence review."
        ),
        "headline_citations": summary_citations,
        "situation_summary": (
            f"The deterministic kernel evaluated {total} proposal(s), with "
            f"{warnings} validation warning(s) and {info} informational finding(s). "
            "This reading guide is not a priority order or an instruction."
        ),
        "summary_citations": summary_citations,
        "observations": observations,
        "questions_for_human": questions,
        "authority_boundary": AUTHORITY_BOUNDARY,
    }


def _validated_model(model: str) -> str:
    if not isinstance(model, str) or not model.strip() or len(model) > 128:
        raise AgentBriefingError("model must be a non-empty short string")
    return model.strip()


def openai_request_body(packet: dict, model: str) -> dict:
    """Build a no-tools Responses request that sets ``store`` to false."""
    model = _validated_model(model)
    return {
        "model": model,
        "store": False,
        "instructions": SYSTEM_INSTRUCTIONS,
        "input": [{
            "role": "user",
            "content": [{
                "type": "input_text",
                "text": "Select opaque citations for a controlled LIFELINE reading guide from this sealed packet:\n" + json.dumps(
                    packet, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
            }],
        }],
        "text": {"format": {
            "type": "json_schema",
            "name": "lifeline_agent_reading_guide",
            "strict": True,
            "schema": GUIDE_SCHEMA,
        }},
    }


def nvidia_request_body(packet: dict, model: str) -> dict:
    """Build a no-tools, non-streaming NVIDIA Chat Completions request.

    NVIDIA documents this endpoint as OpenAI Chat Completions compatible.  We
    deliberately do not rely on provider-specific JSON-mode support: the
    response is parsed then rejected unless it exactly satisfies the same
    closed guide contract used for the OpenAI path.
    """
    model = _validated_model(model)
    packet_text = json.dumps(packet, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {
        "model": model,
        "stream": False,
        "temperature": 0,
        "max_tokens": 512,
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTIONS},
            {
                "role": "user",
                "content": (
                    "Return exactly one JSON object matching the reading-guide "
                    "contract. Select opaque citations only from this sealed packet:\n" + packet_text
                ),
            },
        ],
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


def _nvidia_response_output_text(response: object) -> str:
    if not isinstance(response, dict):
        raise AgentBriefingError("NVIDIA response is not a JSON object")
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise AgentBriefingError("NVIDIA response did not contain a completion choice")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content:
        raise AgentBriefingError("NVIDIA response did not contain text content")
    return content


def _post_json_request(
    url: str,
    body: dict,
    headers: dict[str, str],
    *,
    provider_label: str,
    request_sender: Callable[[Request], bytes] | None,
) -> object:
    request = Request(
        url,
        data=json.dumps(body, separators=(",", ":"), ensure_ascii=True).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        if request_sender is not None:
            raw = request_sender(request)
        else:
            with urlopen(request, timeout=45) as response:
                raw = response.read()
        return json.loads(raw.decode("utf-8"))
    except HTTPError as error:
        raise AgentBriefingError(f"{provider_label} narration request failed with HTTP {error.code}") from error
    except (URLError, TimeoutError) as error:
        raise AgentBriefingError(f"{provider_label} narration request could not be completed") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AgentBriefingError(f"{provider_label} narration response was unreadable") from error


def openai_select_reading_guide(
    packet: dict,
    *,
    model: str,
    api_key: str | None = None,
    request_sender: Callable[[Request], bytes] | None = None,
) -> dict:
    """Call OpenAI only after all deterministic input checks have completed.

    The response is deliberately limited to opaque citation IDs.  It never
    supplies the human-visible text of a briefing.
    """
    secret = api_key or os.environ.get("OPENAI_API_KEY")
    if not secret:
        raise AgentBriefingError("OPENAI_API_KEY is required for optional agent narration")
    response = _post_json_request(
        OPENAI_RESPONSES_URL, openai_request_body(packet, model),
        {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
        provider_label="OpenAI", request_sender=request_sender,
    )
    try:
        guide = json.loads(_response_output_text(response))
    except json.JSONDecodeError as error:
        raise AgentBriefingError("OpenAI reading guide was not valid JSON") from error
    return validate_briefing_guide(guide, packet)


def nvidia_select_reading_guide(
    packet: dict,
    *,
    model: str,
    api_key: str | None = None,
    request_sender: Callable[[Request], bytes] | None = None,
) -> dict:
    """Use NVIDIA only to select citations, then fail closed on its response."""
    secret = api_key or os.environ.get("NVIDIA_API_KEY")
    if not secret:
        raise AgentBriefingError("NVIDIA_API_KEY is required for the NVIDIA development adapter")
    response = _post_json_request(
        NVIDIA_CHAT_COMPLETIONS_URL, nvidia_request_body(packet, model),
        {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
        provider_label="NVIDIA", request_sender=request_sender,
    )
    try:
        guide = json.loads(_nvidia_response_output_text(response))
    except json.JSONDecodeError as error:
        raise AgentBriefingError("NVIDIA reading guide was not valid JSON") from error
    return validate_briefing_guide(guide, packet)


def select_reading_guide(packet: dict, *, provider: str, model: str) -> dict:
    """Dispatch to a configured provider without widening the output contract."""
    if provider == "openai":
        return openai_select_reading_guide(packet, model=model)
    if provider == "nvidia":
        return nvidia_select_reading_guide(packet, model=model)
    raise AgentBriefingError("agent provider must be one of: openai, nvidia")


def agent_artifact(
    inputs: AgentInputs, packet: dict, guide: object, *, model: str, provider: str = "openai"
) -> dict:
    """Bind a controlled, locally rendered reading guide to sealed inputs."""
    normalized_guide = validate_briefing_guide(guide, packet)
    provider_id = _PROVIDER_ARTIFACT_IDS.get(provider)
    if provider_id is None:
        raise AgentBriefingError("agent provider must be one of: openai, nvidia")
    return {
        "agent_briefing_version": AGENT_BRIEFING_VERSION,
        "authority_boundary": AUTHORITY_BOUNDARY,
        "provider": provider_id,
        "model": _validated_model(model),
        "plan_sha256": inputs.plan_sha256,
        "verification_sha256": inputs.verification_sha256,
        "packet_sha256": seal_digest(packet),
        "incident_changes": packet.get("incident_changes", []),
        "guide": normalized_guide,
        "narration": controlled_narration(packet, normalized_guide),
        "limitations": [
            "This is an optional interpretation layer, not a planning or approval artifact.",
            "The agent received no mutation, approval, dispatch, or external-alert tool.",
            "The provider selected opaque citations; all displayed prose was rendered locally from sealed values.",
        ],
    }


def verify_agent_artifact(
    artifact: object,
    inputs: AgentInputs,
    *,
    incident_events: Iterable[object] = (),
) -> None:
    """Check that a controlled briefing remains bound to sealed inputs.

    This verifies integrity, input binding, the citation vocabulary, the
    non-authority contract, and that every displayed sentence equals the local
    controlled rendering for the sealed packet and guide.
    """
    if not isinstance(artifact, dict) or set(artifact) != {
        "agent_briefing_version", "authority_boundary", "provider", "model",
        "plan_sha256", "verification_sha256", "packet_sha256", "incident_changes", "guide", "narration", "limitations",
    }:
        raise AgentBriefingError("agent briefing does not match the artifact contract")
    if artifact.get("agent_briefing_version") != AGENT_BRIEFING_VERSION:
        raise AgentBriefingError("agent briefing has an unsupported version")
    if artifact.get("authority_boundary") != AUTHORITY_BOUNDARY:
        raise AgentBriefingError("agent briefing does not preserve the interpretive-only authority boundary")
    if artifact.get("provider") not in _SUPPORTED_ARTIFACT_PROVIDERS:
        raise AgentBriefingError("agent briefing has an unsupported provider or model")
    _validated_model(artifact.get("model"))
    if artifact.get("plan_sha256") != inputs.plan_sha256 or artifact.get("verification_sha256") != inputs.verification_sha256:
        raise AgentBriefingError("agent briefing is not bound to the current sealed inputs")
    packet = briefing_packet(inputs, incident_changes=artifact.get("incident_changes"))
    supplied_changes = list(incident_events)
    if supplied_changes and packet["incident_changes"] != incident_change_read_model(supplied_changes, inputs):
        raise AgentBriefingError("agent briefing event delta does not match the verified incident ledger")
    if artifact.get("packet_sha256") != seal_digest(packet):
        raise AgentBriefingError("agent briefing packet binding does not match the sealed inputs")
    guide = validate_briefing_guide(artifact.get("guide"), packet)
    if artifact.get("narration") != controlled_narration(packet, guide):
        raise AgentBriefingError("agent briefing narration does not match the controlled local rendering")
    limitations = artifact.get("limitations")
    if not isinstance(limitations, list) or not all(isinstance(item, str) for item in limitations):
        raise AgentBriefingError("agent briefing has invalid limitations")


def write_agent_artifact(out_dir: str | Path, artifact: dict) -> dict:
    """Atomically publish a separately sealed, non-authoritative narration."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    digest = seal_digest(artifact)
    _atomic_write_text(out / "agent_briefing.json", json.dumps(artifact, sort_keys=True, indent=2, ensure_ascii=True) + "\n")
    seal = agent_seal(artifact)
    if seal["sha256"] != digest:  # defensive: one canonical digest source
        raise AgentBriefingError("agent artifact digest changed before sealing")
    _atomic_write_text(out / "agent_briefing.seal.json", json.dumps(seal, sort_keys=True, indent=2, ensure_ascii=True) + "\n")
    return seal


def narrate_export(out_dir: str | Path, *, model: str, provider: str = "openai") -> tuple[dict, dict]:
    """Create and write a provider-assisted guide from verified local artifacts."""
    inputs = load_verified_inputs(out_dir)
    packet = briefing_packet(inputs)
    guide = select_reading_guide(packet, provider=provider, model=model)
    artifact = agent_artifact(inputs, packet, guide, model=model, provider=provider)
    return artifact, write_agent_artifact(out_dir, artifact)


def narrate_incident_plan(
    result: object,
    *,
    model: str,
    provider: str = "openai",
    incident_events: Iterable[object] = (),
) -> tuple[dict, dict]:
    """Narrate one current incident-plan result without writing incident state.

    The caller may return this short-lived sealed response to an authenticated
    local coordinator. No report, plan, approval, or incident revision changes
    merely because a narration was requested.
    """
    inputs = verified_inputs_from_incident_plan(result)
    packet = briefing_packet(inputs, incident_events=incident_events)
    guide = select_reading_guide(packet, provider=provider, model=model)
    artifact = agent_artifact(inputs, packet, guide, model=model, provider=provider)
    return artifact, agent_seal(artifact)


def agent_seal(artifact: dict) -> dict:
    """Return the seal metadata for an agent artifact without persisting it."""
    return {
        "sha256": seal_digest(artifact),
        "canonicalize_version": CANONICALIZE_VERSION,
        "agent_briefing_version": AGENT_BRIEFING_VERSION,
        "seal_version": AGENT_SEAL_VERSION,
        "plan_sha256": artifact["plan_sha256"],
        "verification_sha256": artifact["verification_sha256"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
