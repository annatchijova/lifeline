"""Deterministic, human-approval-only response planning."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Iterable


@dataclass(frozen=True)
class IncidentRequest:
    request_id: str
    people: int
    urgency: int  # 1 (lowest) through 5 (highest), supplied by a verified operator.
    medical_need: bool
    pickup_zone: str
    destination_zone: str


@dataclass(frozen=True)
class Resource:
    resource_id: str
    kind: str
    capacity: int
    available: bool
    can_transport_medical: bool
    zone: str


@dataclass(frozen=True)
class Shelter:
    shelter_id: str
    zone: str
    beds_open: int
    open: bool


@dataclass(frozen=True)
class Route:
    origin: str
    destination: str
    eta_minutes: int
    open: bool


@dataclass(frozen=True)
class DispatchProposal:
    request_id: str
    status: str  # PROPOSED or NEEDS_HUMAN_REVIEW
    resource_id: str | None
    shelter_id: str | None
    eta_minutes: int | None
    reasons: tuple[str, ...]
    audit_hash: str


def _route(routes: Iterable[Route], origin: str, destination: str) -> Route | None:
    matches = [route for route in routes if route.origin == origin and route.destination == destination and route.open]
    return min(matches, key=lambda route: (route.eta_minutes, route.origin, route.destination), default=None)


def _audit_hash(parts: Iterable[str]) -> str:
    return sha256("|".join(parts).encode("utf-8")).hexdigest()


def plan_response(
    requests: Iterable[IncidentRequest],
    resources: Iterable[Resource],
    shelters: Iterable[Shelter],
    routes: Iterable[Route],
) -> list[DispatchProposal]:
    """Create reproducible proposals; never issue a dispatch or recommendation as authority.

    Requests are ordered by declared urgency, then medical need, then the stable ID.
    Each resource and shelter can appear once. All exclusions become audit reasons.
    """
    resource_pool = tuple(sorted(resources, key=lambda resource: resource.resource_id))
    shelter_pool = tuple(sorted(shelters, key=lambda shelter: shelter.shelter_id))
    route_pool = tuple(routes)
    used_resources: set[str] = set()
    reserved_beds: dict[str, int] = {}
    proposals: list[DispatchProposal] = []

    ordered_requests = sorted(
        requests,
        key=lambda request: (-request.urgency, -int(request.medical_need), request.request_id),
    )
    for request in ordered_requests:
        reasons: list[str] = [f"urgency={request.urgency}", f"people={request.people}"]
        eligible_resources = [
            resource for resource in resource_pool
            if resource.available
            and resource.resource_id not in used_resources
            and resource.capacity >= request.people
            and (not request.medical_need or resource.can_transport_medical)
            and _route(route_pool, resource.zone, request.pickup_zone) is not None
        ]
        eligible_shelters = [
            shelter for shelter in shelter_pool
            if shelter.open
            and shelter.beds_open - reserved_beds.get(shelter.shelter_id, 0) >= request.people
            and _route(route_pool, request.pickup_zone, shelter.zone) is not None
        ]

        if not eligible_resources or not eligible_shelters:
            if not eligible_resources:
                reasons.append("no eligible available resource")
            if not eligible_shelters:
                reasons.append("no reachable shelter capacity")
            audit_hash = _audit_hash((request.request_id, "NEEDS_HUMAN_REVIEW", *reasons))
            proposals.append(DispatchProposal(request.request_id, "NEEDS_HUMAN_REVIEW", None, None, None, tuple(reasons), audit_hash))
            continue

        resource = min(
            eligible_resources,
            key=lambda item: (_route(route_pool, item.zone, request.pickup_zone).eta_minutes, item.resource_id),
        )
        shelter = min(
            eligible_shelters,
            key=lambda item: (_route(route_pool, request.pickup_zone, item.zone).eta_minutes, item.shelter_id),
        )
        inbound = _route(route_pool, resource.zone, request.pickup_zone)
        outbound = _route(route_pool, request.pickup_zone, shelter.zone)
        assert inbound is not None and outbound is not None
        eta = inbound.eta_minutes + outbound.eta_minutes
        reasons.extend((f"resource={resource.resource_id}", f"shelter={shelter.shelter_id}", f"eta_minutes={eta}", "human approval required"))
        used_resources.add(resource.resource_id)
        reserved_beds[shelter.shelter_id] = reserved_beds.get(shelter.shelter_id, 0) + request.people
        audit_hash = _audit_hash((request.request_id, "PROPOSED", *reasons))
        proposals.append(DispatchProposal(request.request_id, "PROPOSED", resource.resource_id, shelter.shelter_id, eta, tuple(reasons), audit_hash))

    return proposals
