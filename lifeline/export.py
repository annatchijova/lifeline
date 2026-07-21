"""Canonical serialization, sealing, and incident-room export.

plan.json is the sealed, decision-path artifact: type-tagged canonical
encoding, no floats, SHA-256 digest stored beside it in plan.seal.json.
room.geojson is the display layer: it may carry floats (coordinates) and
is deliberately outside the seal.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from lifeline.briefing import incident_briefing
from lifeline.core import DispatchProposal
from lifeline.scenario import Scenario, load_scenario, plan_scenario, route_usable
from lifeline.validators import Finding, validate_scenario
from lifeline.verification import verification_payload

CANONICALIZE_VERSION = 1
PLAN_VERSION = 3
VERIFICATION_SEAL_VERSION = 1


class CanonicalizationError(ValueError):
    """A value that must never enter a sealed payload was encountered."""


def _atomic_write_text(path: Path, content: str) -> None:
    """Publish one artifact whole-or-not-at-all within its output directory.

    A re-export cannot make an existing public artifact temporarily contain a
    prefix of its replacement.  A crash between sibling publications can still
    leave different generations side by side; their seals deliberately detect
    that state and approval remains fail-closed.
    """
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _tag(value):
    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", str(value)]
    if isinstance(value, float):
        raise CanonicalizationError("float is not allowed in a sealed payload")
    if isinstance(value, str):
        return ["str", value]
    if isinstance(value, (list, tuple)):
        return ["list", [_tag(item) for item in value]]
    if isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise CanonicalizationError(f"non-string dict key {key!r} in sealed payload")
        return ["dict", [[key, _tag(value[key])] for key in sorted(value)]]
    raise CanonicalizationError(f"unsupported type {type(value).__name__} in sealed payload")


def canonicalize(value) -> bytes:
    tagged = {"canonicalize_version": CANONICALIZE_VERSION, "value": _tag(value)}
    return json.dumps(tagged, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def seal_digest(value) -> str:
    return sha256(canonicalize(value)).hexdigest()


def plan_payload(
    scenario: Scenario,
    proposals: list[DispatchProposal],
    findings: tuple[Finding, ...] | list[Finding] = (),
    reference_time: str | None = None,
) -> dict:
    return {
        "plan_version": PLAN_VERSION,
        "scenario_id": scenario.scenario_id,
        "reference_time": reference_time,
        "validation_findings": [finding.as_dict() for finding in findings],
        "proposals": [
            {
                "request_id": proposal.request_id,
                "status": proposal.status,
                "resource_id": proposal.resource_id,
                "shelter_id": proposal.shelter_id,
                "eta_minutes": proposal.eta_minutes,
                "reasons": list(proposal.reasons),
                "audit_hash": proposal.audit_hash,
            }
            for proposal in proposals
        ],
        "briefing": incident_briefing(proposals, findings),
    }


def _point(lon: float, lat: float, properties: dict) -> dict:
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": properties}


def room_geojson(
    scenario: Scenario,
    proposals: list[DispatchProposal],
    findings: tuple[Finding, ...] | list[Finding] = (),
) -> dict:
    zones = {zone.zone_id: zone for zone in scenario.zones}
    outcome = {proposal.request_id: proposal for proposal in proposals}
    finding_codes: dict[tuple[str, str], list[str]] = {}
    for finding in findings:
        finding_codes.setdefault((finding.entity_type, finding.entity_id), []).append(finding.code)

    def codes(entity_type: str, entity_id: str) -> list[str]:
        return finding_codes.get((entity_type, entity_id), [])

    features: list[dict] = []

    for zone in scenario.zones:
        features.append(_point(zone.display_lon, zone.display_lat, {
            "feature_type": "zone", "zone_id": zone.zone_id, "name": zone.name, "kind": zone.kind,
        }))

    per_zone_count: dict[str, int] = {}
    for reported in scenario.requests:
        request = reported.request
        zone = zones[request.pickup_zone]
        shift = per_zone_count.get(request.pickup_zone, 0)
        per_zone_count[request.pickup_zone] = shift + 1
        proposal = outcome[request.request_id]
        features.append(_point(zone.display_lon + 0.0009 * shift, zone.display_lat + 0.0008, {
            "feature_type": "request", "request_id": request.request_id,
            "people": request.people, "urgency": request.urgency, "medical_need": request.medical_need,
            "pickup_zone": request.pickup_zone, "destination_zone": request.destination_zone,
            "status": proposal.status, "resource_id": proposal.resource_id,
            "shelter_id": proposal.shelter_id, "eta_minutes": proposal.eta_minutes,
            "reasons": list(proposal.reasons),
            "source": reported.provenance.source, "source_type": reported.provenance.source_type,
            "observed_at": reported.provenance.observed_at,
            "verification_state": reported.provenance.verification_state,
            "freshness": reported.provenance.freshness,
            "findings": codes("request", request.request_id),
        }))

    assigned = {p.resource_id: p.request_id for p in proposals if p.resource_id is not None}
    for reported in scenario.resources:
        resource = reported.resource
        zone = zones[resource.zone]
        features.append(_point(zone.display_lon, zone.display_lat - 0.0008, {
            "feature_type": "resource", "resource_id": resource.resource_id, "kind": resource.kind,
            "capacity": resource.capacity, "available": resource.available,
            "can_transport_medical": resource.can_transport_medical, "zone": resource.zone,
            "assigned_request": assigned.get(resource.resource_id),
            "source": reported.provenance.source, "source_type": reported.provenance.source_type,
            "observed_at": reported.provenance.observed_at,
            "verification_state": reported.provenance.verification_state,
            "freshness": reported.provenance.freshness,
            "findings": codes("resource", resource.resource_id),
        }))

    for reported in scenario.shelters:
        shelter = reported.shelter
        zone = zones[shelter.zone]
        features.append(_point(zone.display_lon, zone.display_lat, {
            "feature_type": "shelter", "shelter_id": shelter.shelter_id, "zone": shelter.zone,
            "beds_open": shelter.beds_open, "open": shelter.open,
            "source": reported.provenance.source, "source_type": reported.provenance.source_type,
            "observed_at": reported.provenance.observed_at,
            "verification_state": reported.provenance.verification_state,
            "freshness": reported.provenance.freshness,
            "findings": codes("shelter", shelter.shelter_id),
        }))

    for reported in scenario.routes:
        route = reported.route
        origin = zones[route.origin]
        destination = zones[route.destination]
        usable = route_usable(reported)
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [
                [origin.display_lon, origin.display_lat],
                [destination.display_lon, destination.display_lat],
            ]},
            "properties": {
                "feature_type": "route", "origin": route.origin, "destination": route.destination,
                "eta_minutes": route.eta_minutes, "reported_open": route.open, "usable": usable,
                "source": reported.provenance.source, "source_type": reported.provenance.source_type,
                "observed_at": reported.provenance.observed_at,
                "verification_state": reported.provenance.verification_state,
                "freshness": reported.provenance.freshness,
                "findings": codes("route", f"{route.origin}->{route.destination}"),
            },
        })

    return {"type": "FeatureCollection", "features": features}


@dataclass(frozen=True)
class ExportResult:
    seal: dict
    scenario: Scenario
    proposals: list[DispatchProposal]
    findings: list[Finding]


def export_plan(scenario_path: str | Path, out_dir: str | Path, reference_time: str | None = None) -> ExportResult:
    """Validate, corroborate, plan, seal, and write the room artifacts."""
    scenario_path = Path(scenario_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    scenario, findings = validate_scenario(load_scenario(scenario_path), reference_time)
    proposals = plan_scenario(scenario)
    payload = plan_payload(scenario, proposals, findings, reference_time)
    digest = seal_digest(payload)
    verification = verification_payload(scenario, proposals, findings, plan_sha256=digest)
    verification_digest = seal_digest(verification)

    _atomic_write_text(
        out / "plan.json", json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n")
    seal = {
        "sha256": digest,
        "canonicalize_version": CANONICALIZE_VERSION,
        "plan_version": PLAN_VERSION,
        "scenario_sha256": sha256(scenario_path.read_bytes()).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_write_text(
        out / "plan.seal.json", json.dumps(seal, sort_keys=True, indent=2, ensure_ascii=True) + "\n")
    _atomic_write_text(
        out / "verification.json", json.dumps(verification, sort_keys=True, indent=2, ensure_ascii=True) + "\n")
    _atomic_write_text(
        out / "verification.seal.json", json.dumps({
            "sha256": verification_digest,
            "canonicalize_version": CANONICALIZE_VERSION,
            "verification_version": verification["verification_version"],
            "plan_sha256": digest,
            "seal_version": VERIFICATION_SEAL_VERSION,
        }, sort_keys=True, indent=2, ensure_ascii=True) + "\n")
    _atomic_write_text(
        out / "room.geojson", json.dumps(room_geojson(scenario, proposals, findings), indent=2, ensure_ascii=True) + "\n")
    return ExportResult(seal, scenario, proposals, findings)


def export_simulation(
    scenario_path: str | Path,
    whatifs_path: str | Path,
    out_dir: str | Path,
    reference_time: str | None = None,
) -> dict:
    """Run the declared what-if variants and write simulation.json plus its seal."""
    from lifeline.simulate import load_whatifs, simulate_payload

    scenario_path = Path(scenario_path)
    whatifs_path = Path(whatifs_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    scenario = load_scenario(scenario_path)
    simulation_id, variants = load_whatifs(whatifs_path)
    payload = simulate_payload(scenario, simulation_id, variants, reference_time)
    digest = seal_digest(payload)

    _atomic_write_text(
        out / "simulation.json", json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n")
    seal = {
        "sha256": digest,
        "canonicalize_version": CANONICALIZE_VERSION,
        "simulation_version": payload["simulation_version"],
        "scenario_sha256": sha256(scenario_path.read_bytes()).hexdigest(),
        "whatifs_sha256": sha256(whatifs_path.read_bytes()).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_write_text(
        out / "simulation.seal.json", json.dumps(seal, sort_keys=True, indent=2, ensure_ascii=True) + "\n")
    return seal
