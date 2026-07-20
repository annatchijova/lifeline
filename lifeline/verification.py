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
from lifeline.scenario import Provenance, Scenario, route_usable
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

    def as_dict(self) -> dict:
        return {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "source": self.source,
            "source_type": self.source_type,
            "observed_at": self.observed_at,
            "verification_state": self.verification_state,
            "freshness": self.freshness,
            "observation": self.observation.value,
        }


@dataclass(frozen=True)
class VerificationNode:
    request_id: str
    proposal_status: str
    disposition: VerificationDisposition
    reason_code: str
    detail: str
    action_required: str
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
            "action_required": self.action_required,
            "required_artifacts": list(self.required_artifacts),
            "supports": [item.as_dict() for item in self.supports],
            "refutes": [item.as_dict() for item in self.refutes],
            "unresolved": list(self.unresolved),
        }


def _evidence(entity_type: str, entity_id: str, provenance: Provenance) -> EvidenceReference:
    return EvidenceReference(
        entity_type=entity_type,
        entity_id=entity_id,
        source=provenance.source,
        source_type=provenance.source_type,
        observed_at=provenance.observed_at,
        verification_state=provenance.verification_state,
        freshness=provenance.freshness,
    )


def _request_node(request_id: str, proposal: DispatchProposal, provenance: Provenance) -> VerificationNode | None:
    evidence = _evidence("request", request_id, provenance)
    if provenance.verification_state == "conflicting":
        return VerificationNode(
            request_id, proposal.status, VerificationDisposition.BLOCKED,
            "REQUEST_CONTRADICTION",
            "The request report is marked conflicting, so it cannot support a deterministic proposal.",
            "OBTAIN_DISCRIMINATING_EVIDENCE",
            ("independent_authorized_request_confirmation",),
            (evidence,), (),
            ("The competing reports are not resolved by this plan.",),
        )
    if provenance.verification_state != "verified":
        return VerificationNode(
            request_id, proposal.status, VerificationDisposition.BLOCKED,
            "REQUEST_UNVERIFIED",
            "The request report is not verified, so it cannot support a deterministic proposal.",
            "VERIFY_REQUEST_REPORT",
            ("authorized_request_confirmation",),
            (evidence,), (),
            ("The reported request remains unverified.",),
        )
    if provenance.freshness == "low":
        return VerificationNode(
            request_id, proposal.status, VerificationDisposition.BLOCKED,
            "REQUEST_STALE",
            "The request report is stale, so it cannot support a deterministic proposal.",
            "OBTAIN_FRESH_REQUEST_REPORT",
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
        "HUMAN_REVIEW_OF_FEASIBILITY",
        ("human_verified_feasible_resource_route_and_destination_capacity",),
        (), (), reasons or ("The planner recorded a review state without a specific evidence gate.",),
    )


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
        "HUMAN_APPROVAL_REQUIRED",
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
