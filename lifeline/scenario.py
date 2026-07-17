"""Boundary validation and loading for scenario files (schema v1).

All untrusted input enters the system here and nowhere else. Every check
fails closed with a ScenarioError naming the offending entity. Display
coordinates are floats and are display-only by contract: they never reach
the planner or any sealed payload.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from lifeline.core import (
    DispatchProposal,
    IncidentRequest,
    Resource,
    Route,
    Shelter,
    _audit_hash,
    plan_response,
)

SCHEMA_VERSION = 1
VERIFICATION_STATES = ("verified", "unverified", "conflicting")
FRESHNESS_LEVELS = ("high", "medium", "low")


class ScenarioError(ValueError):
    """A scenario file failed boundary validation."""


@dataclass(frozen=True)
class Provenance:
    source: str
    source_type: str
    observed_at: str
    verification_state: str
    freshness: str


@dataclass(frozen=True)
class Zone:
    zone_id: str
    name: str
    kind: str
    display_lon: float  # display-only; never a planning input
    display_lat: float


@dataclass(frozen=True)
class ReportedRequest:
    request: IncidentRequest
    provenance: Provenance


@dataclass(frozen=True)
class ReportedResource:
    resource: Resource
    provenance: Provenance


@dataclass(frozen=True)
class ReportedShelter:
    shelter: Shelter
    provenance: Provenance


@dataclass(frozen=True)
class ReportedRoute:
    route: Route
    provenance: Provenance


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    zones: tuple[Zone, ...]
    requests: tuple[ReportedRequest, ...]
    resources: tuple[ReportedResource, ...]
    shelters: tuple[ReportedShelter, ...]
    routes: tuple[ReportedRoute, ...]


def _require(entry: dict, key: str, kind: type, where: str):
    if key not in entry:
        raise ScenarioError(f"{where}: missing field '{key}'")
    value = entry[key]
    if kind is int and isinstance(value, bool):
        raise ScenarioError(f"{where}: field '{key}' must be an integer, got a boolean")
    if kind is float and isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, kind):
        raise ScenarioError(f"{where}: field '{key}' must be {kind.__name__}, got {type(value).__name__}")
    return value


def _provenance(entry: dict, where: str) -> Provenance:
    state = _require(entry, "verification_state", str, where)
    if state not in VERIFICATION_STATES:
        raise ScenarioError(f"{where}: unknown verification_state '{state}'")
    freshness = _require(entry, "freshness", str, where)
    if freshness not in FRESHNESS_LEVELS:
        raise ScenarioError(f"{where}: unknown freshness '{freshness}'")
    return Provenance(
        source=_require(entry, "source", str, where),
        source_type=_require(entry, "source_type", str, where),
        observed_at=_require(entry, "observed_at", str, where),
        verification_state=state,
        freshness=freshness,
    )


def _zone_ref(zone_id: str, zone_ids: frozenset[str], where: str) -> str:
    if zone_id not in zone_ids:
        raise ScenarioError(f"{where}: unknown zone '{zone_id}'")
    return zone_id


def _positive(value: int, field: str, where: str) -> int:
    if value <= 0:
        raise ScenarioError(f"{where}: field '{field}' must be positive, got {value}")
    return value


def _unique(seen: set[str], identifier: str, where: str) -> str:
    if identifier in seen:
        raise ScenarioError(f"{where}: duplicate id '{identifier}'")
    seen.add(identifier)
    return identifier


def parse_scenario(raw: dict) -> Scenario:
    if not isinstance(raw, dict):
        raise ScenarioError("scenario: top level must be an object")
    version = raw.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ScenarioError(f"scenario: unsupported schema_version {version!r}, expected {SCHEMA_VERSION}")
    scenario_id = _require(raw, "scenario_id", str, "scenario")

    zones: list[Zone] = []
    zone_seen: set[str] = set()
    for entry in raw.get("zones", []):
        zone_id = _unique(zone_seen, _require(entry, "zone_id", str, "zone"), "zone")
        where = f"zone '{zone_id}'"
        display = _require(entry, "display", dict, where)
        lon = _require(display, "lon", float, where)
        lat = _require(display, "lat", float, where)
        if not -180.0 <= lon <= 180.0:
            raise ScenarioError(f"{where}: lon {lon} out of range [-180, 180]")
        if not -90.0 <= lat <= 90.0:
            raise ScenarioError(f"{where}: lat {lat} out of range [-90, 90]")
        zones.append(Zone(zone_id, _require(entry, "name", str, where), _require(entry, "kind", str, where), lon, lat))
    if not zones:
        raise ScenarioError("scenario: at least one zone is required")
    zone_ids = frozenset(zone_seen)

    requests: list[ReportedRequest] = []
    request_seen: set[str] = set()
    for entry in raw.get("requests", []):
        request_id = _unique(request_seen, _require(entry, "request_id", str, "request"), "request")
        where = f"request '{request_id}'"
        urgency = _require(entry, "urgency", int, where)
        if not 1 <= urgency <= 5:
            raise ScenarioError(f"{where}: urgency must be 1 through 5, got {urgency}")
        requests.append(ReportedRequest(
            IncidentRequest(
                request_id=request_id,
                people=_positive(_require(entry, "people", int, where), "people", where),
                urgency=urgency,
                medical_need=_require(entry, "medical_need", bool, where),
                pickup_zone=_zone_ref(_require(entry, "pickup_zone", str, where), zone_ids, where),
                destination_zone=_zone_ref(_require(entry, "destination_zone", str, where), zone_ids, where),
            ),
            _provenance(entry, where),
        ))

    resources: list[ReportedResource] = []
    resource_seen: set[str] = set()
    for entry in raw.get("resources", []):
        resource_id = _unique(resource_seen, _require(entry, "resource_id", str, "resource"), "resource")
        where = f"resource '{resource_id}'"
        resources.append(ReportedResource(
            Resource(
                resource_id=resource_id,
                kind=_require(entry, "kind", str, where),
                capacity=_positive(_require(entry, "capacity", int, where), "capacity", where),
                available=_require(entry, "available", bool, where),
                can_transport_medical=_require(entry, "can_transport_medical", bool, where),
                zone=_zone_ref(_require(entry, "zone", str, where), zone_ids, where),
            ),
            _provenance(entry, where),
        ))

    shelters: list[ReportedShelter] = []
    shelter_seen: set[str] = set()
    for entry in raw.get("shelters", []):
        shelter_id = _unique(shelter_seen, _require(entry, "shelter_id", str, "shelter"), "shelter")
        where = f"shelter '{shelter_id}'"
        beds_open = _require(entry, "beds_open", int, where)
        if beds_open < 0:
            raise ScenarioError(f"{where}: beds_open must not be negative, got {beds_open}")
        shelters.append(ReportedShelter(
            Shelter(
                shelter_id=shelter_id,
                zone=_zone_ref(_require(entry, "zone", str, where), zone_ids, where),
                beds_open=beds_open,
                open=_require(entry, "open", bool, where),
            ),
            _provenance(entry, where),
        ))

    routes: list[ReportedRoute] = []
    for index, entry in enumerate(raw.get("routes", [])):
        where = f"route #{index}"
        routes.append(ReportedRoute(
            Route(
                origin=_zone_ref(_require(entry, "origin", str, where), zone_ids, where),
                destination=_zone_ref(_require(entry, "destination", str, where), zone_ids, where),
                eta_minutes=_positive(_require(entry, "eta_minutes", int, where), "eta_minutes", where),
                open=_require(entry, "open", bool, where),
            ),
            _provenance(entry, where),
        ))

    return Scenario(scenario_id, tuple(zones), tuple(requests), tuple(resources), tuple(shelters), tuple(routes))


def load_scenario(path: str | Path) -> Scenario:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ScenarioError(f"scenario: invalid JSON ({error})") from error
    return parse_scenario(raw)


def route_usable(reported: ReportedRoute) -> bool:
    """Planning may never rely on closed, stale, or conflicting routes."""
    return (
        reported.route.open
        and reported.provenance.verification_state == "verified"
        and reported.provenance.freshness != "low"
    )


def operational_evidence_usable(provenance: Provenance) -> bool:
    """Whether a reported resource or shelter may constrain a proposal.

    A resource that is merely claimed to be available, or a shelter with stale
    capacity, is still displayed with its provenance but may not silently
    enter the deterministic proposal path.
    """
    return provenance.verification_state == "verified" and provenance.freshness != "low"


def plan_scenario(scenario: Scenario) -> list[DispatchProposal]:
    """Gate unverified evidence, then run the deterministic planner.

    Only verified, non-stale operational evidence may influence a proposal.
    Unverified or conflicting requests surface as NEEDS_HUMAN_REVIEW instead
    of being silently planned or silently dropped. Resources, shelters, and
    routes with unverified, conflicting, or low-freshness evidence remain in
    the display layer but are excluded from planning.
    """
    gated: list[DispatchProposal] = []
    verified_requests: list[IncidentRequest] = []
    for reported in scenario.requests:
        state = reported.provenance.verification_state
        if state == "verified":
            verified_requests.append(reported.request)
            continue
        reason = "unverified report" if state == "unverified" else "conflicting reports"
        reasons = (f"urgency={reported.request.urgency}", f"people={reported.request.people}", reason)
        audit_hash = _audit_hash((reported.request.request_id, "NEEDS_HUMAN_REVIEW", *reasons))
        gated.append(DispatchProposal(reported.request.request_id, "NEEDS_HUMAN_REVIEW", None, None, None, reasons, audit_hash))

    usable_routes = [
        Route(item.route.origin, item.route.destination, item.route.eta_minutes, route_usable(item))
        for item in scenario.routes
    ]
    planned = plan_response(
        verified_requests,
        [item.resource for item in scenario.resources if operational_evidence_usable(item.provenance)],
        [item.shelter for item in scenario.shelters if operational_evidence_usable(item.provenance)],
        usable_routes,
    )

    by_request = {reported.request.request_id: reported.request for reported in scenario.requests}
    merged = planned + gated
    merged.sort(key=lambda proposal: (
        -by_request[proposal.request_id].urgency,
        -int(by_request[proposal.request_id].medical_need),
        proposal.request_id,
    ))
    return merged
