"""Deterministic evidence-gap read model for human verification.

The planner remains the only component that determines feasibility.  This
module explains a completed plan's evidence boundary: it records which
proposal is blocked, the observed report state, and the discriminating
evidence a human would need before the plan can be recomputed.  It neither
prioritizes people nor issues a dispatch instruction.

The contract follows VIGÍA's reasoning-trace discipline without importing its
forensic domain: an observation that was not analyzed is never treated as a
fact, contradictions remain visible, and a blocked result names the evidence
required to revisit it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from lifeline.core import DispatchProposal
from lifeline.scenario import Provenance, Scenario, operational_evidence_usable, route_usable
from lifeline.validators import Finding

VERIFICATION_VERSION = 1


class ObservationState(str, Enum):
    """Whether a report was actually examined by the deterministic boundary."""

    ANALYZED = "ANALYZED"
    NOT_ANALYZED = "NOT_ANALYZED"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"


class VerificationDisposition(str, Enum):
    """A verification state, never an operational command."""

    CLEAR = "CLEAR"
    BLOCKED = "BLOCKED"


class VerificationAction(str, Enum):
    """The closed, non-authoritative vocabulary emitted by verification nodes."""

    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"
    VERIFY_REQUEST_REPORT = "VERIFY_REQUEST_REPORT"
    OBTAIN_DISCRIMINATING_EVIDENCE = "OBTAIN_DISCRIMINATING_EVIDENCE"
    OBTAIN_FRESH_REQUEST_REPORT = "OBTAIN_FRESH_REQUEST_REPORT"
    HUMAN_REVIEW_OF_FEASIBILITY = "HUMAN_REVIEW_OF_FEASIBILITY"
    OBTAIN_DISCRIMINATING_ROUTE_EVIDENCE = "OBTAIN_DISCRIMINATING_ROUTE_EVIDENCE"
    VERIFY_CURRENT_ROUTE_STATUS = "VERIFY_CURRENT_ROUTE_STATUS"
    OBTAIN_DISCRIMINATING_ACCESS_ROUTE_EVIDENCE = "OBTAIN_DISCRIMINATING_ACCESS_ROUTE_EVIDENCE"
    VERIFY_CURRENT_ACCESS_ROUTE_STATUS = "VERIFY_CURRENT_ACCESS_ROUTE_STATUS"
    VERIFY_CURRENT_RESOURCE_AVAILABILITY = "VERIFY_CURRENT_RESOURCE_AVAILABILITY"
    VERIFY_CURRENT_DESTINATION_CAPACITY = "VERIFY_CURRENT_DESTINATION_CAPACITY"


CLEAR_ACTION = VerificationAction.HUMAN_APPROVAL_REQUIRED.value
BLOCKED_ACTIONS = frozenset(
    action.value for action in VerificationAction
    if action is not VerificationAction.HUMAN_APPROVAL_REQUIRED
)


class VerificationError(ValueError):
    """A sealed verification payload violates LIFELINE's authority boundary."""


@dataclass(frozen=True)
class EvidenceReference:
    entity_type: str
    entity_id: str
    source: str
    source_type: str
    observed_at: str
    verification_state: str
    freshness: str
    observation: ObservationState = ObservationState.ANALYZED
    assertion: str | None = None

    def as_dict(self) -> dict:
        payload = {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "source": self.source,
            "source_type": self.source_type,
            "observed_at": self.observed_at,
            "verification_state": self.verification_state,
            "freshness": self.freshness,
            "observation": self.observation.value,
        }
        if self.assertion is not None:
            payload["assertion"] = self.assertion
        return payload


@dataclass(frozen=True)
class VerificationNode:
    request_id: str
    proposal_status: str
    disposition: VerificationDisposition
    reason_code: str
    detail: str
    action_required: VerificationAction
    required_artifacts: tuple[str, ...]
    supports: tuple[EvidenceReference, ...]
    refutes: tuple[EvidenceReference, ...]
    unresolved: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "proposal_status": self.proposal_status,
            "disposition": self.disposition.value,
            "reason_code": self.reason_code,
            "detail": self.detail,
            "action_required": self.action_required.value,
            "required_artifacts": list(self.required_artifacts),
            "supports": [item.as_dict() for item in self.supports],
            "refutes": [item.as_dict() for item in self.refutes],
            "unresolved": list(self.unresolved),
        }


def _evidence(
    entity_type: str,
    entity_id: str,
    provenance: Provenance,
    *,
    assertion: str | None = None,
) -> EvidenceReference:
    return EvidenceReference(
        entity_type=entity_type,
        entity_id=entity_id,
        source=provenance.source,
        source_type=provenance.source_type,
        observed_at=provenance.observed_at,
        verification_state=provenance.verification_state,
        freshness=provenance.freshness,
        assertion=assertion,
    )


def _request_node(request_id: str, proposal: DispatchProposal, provenance: Provenance) -> VerificationNode | None:
    evidence = _evidence("request", request_id, provenance)
    if provenance.verification_state == "conflicting":
        return VerificationNode(
            request_id, proposal.status, VerificationDisposition.BLOCKED,
            "REQUEST_CONTRADICTION",
            "The request report is marked conflicting, so it cannot support a deterministic proposal.",
            VerificationAction.OBTAIN_DISCRIMINATING_EVIDENCE,
            ("independent_authorized_request_confirmation",),
            (evidence,), (),
            ("The competing reports are not resolved by this plan.",),
        )
    if provenance.verification_state != "verified":
        return VerificationNode(
            request_id, proposal.status, VerificationDisposition.BLOCKED,
            "REQUEST_UNVERIFIED",
            "The request report is not verified, so it cannot support a deterministic proposal.",
            VerificationAction.VERIFY_REQUEST_REPORT,
            ("authorized_request_confirmation",),
            (evidence,), (),
            ("The reported request remains unverified.",),
        )
    if provenance.freshness == "low":
        return VerificationNode(
            request_id, proposal.status, VerificationDisposition.BLOCKED,
            "REQUEST_STALE",
            "The request report is stale, so it cannot support a deterministic proposal.",
            VerificationAction.OBTAIN_FRESH_REQUEST_REPORT,
            ("fresh_authorized_request_report",),
            (evidence,), (),
            ("The plan cannot establish that the request is still current.",),
        )
    return None


def _feasibility_node(request_id: str, proposal: DispatchProposal) -> VerificationNode:
    reasons = tuple(reason for reason in proposal.reasons if reason.startswith("no "))
    return VerificationNode(
        request_id, proposal.status, VerificationDisposition.BLOCKED,
        "FEASIBILITY_NOT_ESTABLISHED",
        "The deterministic planner could not establish a feasible proposal from the verified, current evidence.",
        VerificationAction.HUMAN_REVIEW_OF_FEASIBILITY,
        ("human_verified_feasible_resource_route_and_destination_capacity",),
        (), (), reasons or ("The planner recorded a review state without a specific evidence gate.",),
    )


def _route_evidence_nodes(scenario: Scenario, request_id: str, proposal: DispatchProposal) -> list[VerificationNode]:
    """Expose non-usable destination-route reports without inventing a route."""
    request = next(item for item in scenario.requests if item.request.request_id == request_id).request
    candidates = [
        item for item in scenario.routes
        if item.route.origin == request.pickup_zone and item.route.destination == request.destination_zone
    ]
    if not candidates or all(route_usable(item) for item in candidates):
        return []
    route_id = f"{request.pickup_zone}->{request.destination_zone}"
    supports = tuple(
        _evidence("route", route_id, item.provenance, assertion="route_reported_open")
        for item in candidates if item.route.open
    )
    refutes = tuple(
        _evidence("route", route_id, item.provenance, assertion="route_reported_closed")
        for item in candidates if not item.route.open
    )
    if supports and refutes:
        reason_code = "ROUTE_CONTRADICTION"
        detail = "Conflicting route reports prevent the destination route from supporting a deterministic proposal."
        action = VerificationAction.OBTAIN_DISCRIMINATING_ROUTE_EVIDENCE
    else:
        reason_code = "ROUTE_EVIDENCE_UNUSABLE"
        detail = "The reported destination route is not verified and fresh enough to support a deterministic proposal."
        action = VerificationAction.VERIFY_CURRENT_ROUTE_STATUS
    return [VerificationNode(
        request_id, proposal.status, VerificationDisposition.BLOCKED,
        reason_code, detail, action,
        ("independent_current_route_status",), supports, refutes,
        (f"No usable evidence establishes route {route_id} for this proposal.",),
    )]


def _access_route_evidence_nodes(scenario: Scenario, request_id: str, proposal: DispatchProposal) -> list[VerificationNode]:
    """Expose access-route evidence that prevents a candidate resource arriving."""
    request = next(item for item in scenario.requests if item.request.request_id == request_id).request
    nodes = []
    for reported_resource in sorted(scenario.resources, key=lambda item: item.resource.resource_id):
        resource = reported_resource.resource
        if not (
            resource.available
            and resource.capacity >= request.people
            and (not request.medical_need or resource.can_transport_medical)
        ):
            continue
        candidates = [
            item for item in scenario.routes
            if item.route.origin == resource.zone and item.route.destination == request.pickup_zone
        ]
        if not candidates or all(route_usable(item) for item in candidates):
            continue
        route_id = f"{resource.zone}->{request.pickup_zone}"
        supports = tuple(
            _evidence("route", route_id, item.provenance, assertion="access_route_reported_open")
            for item in candidates if item.route.open
        )
        refutes = tuple(
            _evidence("route", route_id, item.provenance, assertion="access_route_reported_closed")
            for item in candidates if not item.route.open
        )
        if supports and refutes:
            reason_code = "ACCESS_ROUTE_CONTRADICTION"
            detail = "Conflicting access-route reports prevent this resource from reaching the pickup zone."
            action = VerificationAction.OBTAIN_DISCRIMINATING_ACCESS_ROUTE_EVIDENCE
        else:
            reason_code = "ACCESS_ROUTE_EVIDENCE_UNUSABLE"
            detail = "The reported access route is not verified and fresh enough for this resource to reach the pickup zone."
            action = VerificationAction.VERIFY_CURRENT_ACCESS_ROUTE_STATUS
        nodes.append(VerificationNode(
            request_id, proposal.status, VerificationDisposition.BLOCKED,
            reason_code, detail, action,
            ("independent_current_access_route_status",), supports, refutes,
            (f"Resource {resource.resource_id} cannot use route {route_id} in the deterministic plan.",),
        ))
    return nodes


def _reported_open_route_exists(scenario: Scenario, origin: str, destination: str) -> bool:
    return any(
        item.route.origin == origin and item.route.destination == destination and item.route.open
        for item in scenario.routes
    )


def _resource_evidence_nodes(scenario: Scenario, request_id: str, proposal: DispatchProposal) -> list[VerificationNode]:
    request = next(item for item in scenario.requests if item.request.request_id == request_id).request
    nodes = []
    for reported in sorted(scenario.resources, key=lambda item: item.resource.resource_id):
        resource = reported.resource
        factual_candidate = (
            resource.available
            and resource.capacity >= request.people
            and (not request.medical_need or resource.can_transport_medical)
            and _reported_open_route_exists(scenario, resource.zone, request.pickup_zone)
        )
        if not factual_candidate or operational_evidence_usable(reported.provenance):
            continue
        evidence = _evidence(
            "resource", resource.resource_id, reported.provenance,
            assertion="resource_reported_available",
        )
        nodes.append(VerificationNode(
            request_id, proposal.status, VerificationDisposition.BLOCKED,
            "RESOURCE_EVIDENCE_UNUSABLE",
            "A resource meets the declared capacity and compatibility constraints but its availability evidence is not verified and fresh enough for planning.",
            VerificationAction.VERIFY_CURRENT_RESOURCE_AVAILABILITY,
            ("verified_current_resource_availability",), (evidence,), (),
            (f"Resource {resource.resource_id} remains excluded from the deterministic resource pool.",),
        ))
    return nodes


def _shelter_evidence_nodes(scenario: Scenario, request_id: str, proposal: DispatchProposal) -> list[VerificationNode]:
    request = next(item for item in scenario.requests if item.request.request_id == request_id).request
    nodes = []
    for reported in sorted(scenario.shelters, key=lambda item: item.shelter.shelter_id):
        shelter = reported.shelter
        factual_candidate = (
            shelter.open
            and shelter.zone == request.destination_zone
            and shelter.beds_open >= request.people
            and _reported_open_route_exists(scenario, request.pickup_zone, shelter.zone)
        )
        if not factual_candidate or operational_evidence_usable(reported.provenance):
            continue
        evidence = _evidence(
            "shelter", shelter.shelter_id, reported.provenance,
            assertion="shelter_reported_capacity_available",
        )
        nodes.append(VerificationNode(
            request_id, proposal.status, VerificationDisposition.BLOCKED,
            "SHELTER_EVIDENCE_UNUSABLE",
            "A destination shelter has declared capacity but its availability evidence is not verified and fresh enough for planning.",
            VerificationAction.VERIFY_CURRENT_DESTINATION_CAPACITY,
            ("verified_current_destination_capacity",), (evidence,), (),
            (f"Shelter {shelter.shelter_id} remains excluded from the deterministic shelter pool.",),
        ))
    return nodes


def _selected_route(scenario: Scenario, origin: str, destination: str):
    candidates = [
        item for item in scenario.routes
        if item.route.origin == origin and item.route.destination == destination and route_usable(item)
    ]
    return min(candidates, key=lambda item: (item.route.eta_minutes, item.route.origin, item.route.destination), default=None)


def _clear_evidence(scenario: Scenario, request_id: str, proposal: DispatchProposal) -> tuple[EvidenceReference, ...]:
    request = next(item for item in scenario.requests if item.request.request_id == request_id)
    references = [_evidence("request", request_id, request.provenance)]
    if proposal.resource_id is None or proposal.shelter_id is None:
        return tuple(references)
    resource = next(item for item in scenario.resources if item.resource.resource_id == proposal.resource_id)
    shelter = next(item for item in scenario.shelters if item.shelter.shelter_id == proposal.shelter_id)
    references.extend((
        _evidence("resource", resource.resource.resource_id, resource.provenance),
        _evidence("shelter", shelter.shelter.shelter_id, shelter.provenance),
    ))
    for route in (
        _selected_route(scenario, resource.resource.zone, request.request.pickup_zone),
        _selected_route(scenario, request.request.pickup_zone, shelter.shelter.zone),
    ):
        if route is not None:
            route_id = f"{route.route.origin}->{route.route.destination}"
            references.append(_evidence("route", route_id, route.provenance))
    return tuple(references)


def _clear_node(scenario: Scenario, request_id: str, proposal: DispatchProposal) -> VerificationNode:
    return VerificationNode(
        request_id, proposal.status, VerificationDisposition.CLEAR,
        "EVIDENCE_GATES_CLEAR",
        "The deterministic evidence gates required for this proposal were satisfied.",
        VerificationAction.HUMAN_APPROVAL_REQUIRED,
        (), _clear_evidence(scenario, request_id, proposal), (), (),
    )


def verification_payload(
    scenario: Scenario,
    proposals: list[DispatchProposal],
    findings: tuple[Finding, ...] | list[Finding],
    *,
    plan_sha256: str,
) -> dict:
    """Return the complete, deterministic evidence-gap artifact for a plan.

    A proposal may have more than one node: an unverified request and an
    independent feasibility gap must both remain visible.  Nodes are ordered
    by the plan order and then by stable reason code; no urgency-derived score
    is introduced here.
    """
    requests = {reported.request.request_id: reported for reported in scenario.requests}
    nodes: list[VerificationNode] = []
    for proposal in proposals:
        reported = requests[proposal.request_id]
        request_node = _request_node(proposal.request_id, proposal, reported.provenance)
        if request_node is not None:
            nodes.append(request_node)
        elif proposal.status == "PROPOSED":
            nodes.append(_clear_node(scenario, proposal.request_id, proposal))
        if proposal.status == "NEEDS_HUMAN_REVIEW" and any(
            reason.startswith("no ") for reason in proposal.reasons
        ):
            nodes.extend(_resource_evidence_nodes(scenario, proposal.request_id, proposal))
            nodes.extend(_shelter_evidence_nodes(scenario, proposal.request_id, proposal))
            nodes.extend(_access_route_evidence_nodes(scenario, proposal.request_id, proposal))
            nodes.extend(_route_evidence_nodes(scenario, proposal.request_id, proposal))
            nodes.append(_feasibility_node(proposal.request_id, proposal))

    nodes.sort(key=lambda node: (node.request_id, node.reason_code))
    finding_dicts = [finding.as_dict() for finding in findings]
    return {
        "verification_version": VERIFICATION_VERSION,
        "scenario_id": scenario.scenario_id,
        "plan_sha256": plan_sha256,
        "nodes": [node.as_dict() for node in nodes],
        "validation_findings": finding_dicts,
        "limitations": [
            "This artifact names evidence gaps and human verification work; it is not a priority score or dispatch authority.",
            "A required artifact allows a plan to be recomputed after human verification; it does not guarantee a feasible proposal.",
            "Only reports represented in the scenario are analyzed. Unreported conditions remain outside this artifact's evidence boundary.",
        ],
    }


def verify_payload(
    payload: dict,
    plan: dict,
    *,
    expected_plan_sha256: str,
) -> None:
    """Verify the domain-neutral contract beyond its cryptographic seal.

    A SHA-256 seal establishes that bytes have not changed since sealing.  This
    check establishes that those bytes still describe the plan they claim to
    explain and have not crossed LIFELINE's no-dispatch authority boundary.
    It deliberately validates the contract, not operational truth: a changed
    field report must be represented in a new scenario and recomputed plan.
    """
    if not isinstance(payload, dict) or not isinstance(plan, dict):
        raise VerificationError("verification payload and plan must be objects")
    if payload.get("verification_version") != VERIFICATION_VERSION:
        raise VerificationError("unsupported verification_version")
    if payload.get("plan_sha256") != expected_plan_sha256:
        raise VerificationError("verification payload is not bound to the sealed plan")

    proposals = plan.get("proposals")
    if not isinstance(proposals, list):
        raise VerificationError("plan proposals must be a list")
    proposal_statuses: dict[str, str] = {}
    for proposal in proposals:
        if not isinstance(proposal, dict):
            raise VerificationError("plan proposal must be an object")
        request_id = proposal.get("request_id")
        status = proposal.get("status")
        if not isinstance(request_id, str) or not request_id:
            raise VerificationError("plan proposal is missing request_id")
        if request_id in proposal_statuses:
            raise VerificationError(f"plan has duplicate proposal for {request_id}")
        if status not in {"PROPOSED", "NEEDS_HUMAN_REVIEW"}:
            raise VerificationError(f"plan proposal {request_id} has unsupported status")
        proposal_statuses[request_id] = status

    nodes = payload.get("nodes")
    if not isinstance(nodes, list):
        raise VerificationError("verification nodes must be a list")
    seen_node_keys: set[tuple[str, str]] = set()
    covered_requests: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            raise VerificationError("verification node must be an object")
        request_id = node.get("request_id")
        reason_code = node.get("reason_code")
        if not isinstance(request_id, str) or request_id not in proposal_statuses:
            raise VerificationError("verification node references no plan proposal")
        if not isinstance(reason_code, str) or not reason_code:
            raise VerificationError(f"verification node for {request_id} is missing reason_code")
        node_key = (request_id, reason_code)
        if node_key in seen_node_keys:
            raise VerificationError(f"verification payload has duplicate node {request_id}:{reason_code}")
        seen_node_keys.add(node_key)
        covered_requests.add(request_id)

        status = proposal_statuses[request_id]
        if node.get("proposal_status") != status:
            raise VerificationError(f"verification node status disagrees with plan for {request_id}")
        disposition = node.get("disposition")
        if disposition not in {item.value for item in VerificationDisposition}:
            raise VerificationError(f"verification node has unsupported disposition for {request_id}")
        if status == "PROPOSED" and disposition != VerificationDisposition.CLEAR.value:
            raise VerificationError(f"proposed request {request_id} must have a CLEAR verification node")
        if status == "NEEDS_HUMAN_REVIEW" and disposition != VerificationDisposition.BLOCKED.value:
            raise VerificationError(f"review request {request_id} must have a BLOCKED verification node")

        action = node.get("action_required")
        if not isinstance(action, str) or not action:
            raise VerificationError(f"verification node for {request_id} is missing action_required")
        artifacts = node.get("required_artifacts")
        if not isinstance(artifacts, list) or not all(isinstance(item, str) and item for item in artifacts):
            raise VerificationError(f"verification node for {request_id} has invalid required_artifacts")
        if disposition == VerificationDisposition.CLEAR.value:
            if reason_code != "EVIDENCE_GATES_CLEAR":
                raise VerificationError(f"clear node for {request_id} has an invalid reason_code")
            if action != CLEAR_ACTION or artifacts:
                raise VerificationError(f"clear node for {request_id} crosses the human-approval boundary")
        elif action not in BLOCKED_ACTIONS:
            raise VerificationError(f"blocked node for {request_id} has an unknown verification action")

        for field in ("supports", "refutes", "unresolved"):
            if not isinstance(node.get(field), list):
                raise VerificationError(f"verification node for {request_id} has invalid {field}")

    missing = set(proposal_statuses) - covered_requests
    if missing:
        raise VerificationError(
            "verification payload omits plan proposal(s): " + ", ".join(sorted(missing))
        )
