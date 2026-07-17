"""Explicit what-if simulation: compare alternatives, never pick a winner.

Each variant is a declared set of overrides on the base scenario ("north
bridge confirmed closed", "shelter capacity reduced"). The variant scenario
is re-corroborated and re-planned by the same deterministic pipeline, and
the output records the differences against the base plan. No score ranks
the variants and no winner is chosen: the point is to expose dependencies
and fragility to the human who decides. Simulated results are never live
facts and the sealed payload says so.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from lifeline.core import DispatchProposal
from lifeline.scenario import (
    FRESHNESS_LEVELS,
    ReportedRequest,
    ReportedResource,
    ReportedRoute,
    ReportedShelter,
    Scenario,
    VERIFICATION_STATES,
    plan_scenario,
)
from lifeline.validators import validate_scenario

SIMULATION_VERSION = 1

LIMITATIONS = (
    "simulation over synthetic or explicitly authorized data only; results are not live facts",
    "unmodelled: travel-time variability, weather, fuel, crew availability, secondary hazards",
    "no winner is selected; a human compares the alternatives and decides",
)

_PROVENANCE_FIELDS = {"verification_state", "freshness"}
_SETTABLE = {
    "route": {"open": bool, "eta_minutes": int, "verification_state": str, "freshness": str},
    "resource": {"available": bool, "capacity": int, "can_transport_medical": bool,
                 "verification_state": str, "freshness": str},
    "shelter": {"beds_open": int, "open": bool, "verification_state": str, "freshness": str},
    "request": {"people": int, "urgency": int, "medical_need": bool,
                "verification_state": str, "freshness": str},
}


class SimulationError(ValueError):
    """A what-if file failed boundary validation or targets a missing entity."""


@dataclass(frozen=True)
class VariantSpec:
    variant_id: str
    label: str
    assumptions: tuple[str, ...]
    overrides: tuple[dict, ...]


def _check_set(kind: str, changes: dict, where: str) -> None:
    allowed = _SETTABLE[kind]
    if not changes:
        raise SimulationError(f"{where}: empty 'set'")
    for field, value in changes.items():
        if field not in allowed:
            raise SimulationError(f"{where}: field '{field}' is not settable on a {kind}")
        expected = allowed[field]
        if expected is int and isinstance(value, bool):
            raise SimulationError(f"{where}: field '{field}' must be an integer, got a boolean")
        if not isinstance(value, expected):
            raise SimulationError(f"{where}: field '{field}' must be {expected.__name__}")
    if "verification_state" in changes and changes["verification_state"] not in VERIFICATION_STATES:
        raise SimulationError(f"{where}: unknown verification_state '{changes['verification_state']}'")
    if "freshness" in changes and changes["freshness"] not in FRESHNESS_LEVELS:
        raise SimulationError(f"{where}: unknown freshness '{changes['freshness']}'")
    if "eta_minutes" in changes and changes["eta_minutes"] <= 0:
        raise SimulationError(f"{where}: eta_minutes must be positive")
    if "people" in changes and changes["people"] <= 0:
        raise SimulationError(f"{where}: people must be positive")
    if "urgency" in changes and not 1 <= changes["urgency"] <= 5:
        raise SimulationError(f"{where}: urgency must be 1 through 5")
    if "capacity" in changes and changes["capacity"] <= 0:
        raise SimulationError(f"{where}: capacity must be positive")
    if "beds_open" in changes and changes["beds_open"] < 0:
        raise SimulationError(f"{where}: beds_open must not be negative")


def parse_whatifs(raw: dict) -> tuple[str, list[VariantSpec]]:
    if not isinstance(raw, dict):
        raise SimulationError("whatifs: top level must be an object")
    if raw.get("schema_version") != SIMULATION_VERSION:
        raise SimulationError(f"whatifs: unsupported schema_version {raw.get('schema_version')!r}")
    simulation_id = raw.get("simulation_id")
    if not isinstance(simulation_id, str) or not simulation_id:
        raise SimulationError("whatifs: missing simulation_id")

    variants: list[VariantSpec] = []
    seen: set[str] = set()
    for entry in raw.get("variants", []):
        variant_id = entry.get("variant_id")
        if not isinstance(variant_id, str) or not variant_id:
            raise SimulationError("whatifs: variant without variant_id")
        if variant_id in seen:
            raise SimulationError(f"whatifs: duplicate variant_id '{variant_id}'")
        seen.add(variant_id)
        where = f"variant '{variant_id}'"
        label = entry.get("label")
        if not isinstance(label, str) or not label:
            raise SimulationError(f"{where}: missing label")
        assumptions = entry.get("assumptions", [])
        if not isinstance(assumptions, list) or not all(isinstance(a, str) for a in assumptions) or not assumptions:
            raise SimulationError(f"{where}: assumptions must be a non-empty list of strings")
        overrides = entry.get("overrides", [])
        if not isinstance(overrides, list) or not overrides:
            raise SimulationError(f"{where}: overrides must be a non-empty list")
        for override in overrides:
            kind = override.get("kind")
            if kind not in _SETTABLE:
                raise SimulationError(f"{where}: unknown override kind {kind!r}")
            if kind == "route":
                if not isinstance(override.get("origin"), str) or not isinstance(override.get("destination"), str):
                    raise SimulationError(f"{where}: route override needs origin and destination")
            elif not isinstance(override.get("id"), str) or not override.get("id"):
                raise SimulationError(f"{where}: {kind} override needs 'id'")
            if not isinstance(override.get("set"), dict):
                raise SimulationError(f"{where}: override needs a 'set' object")
            _check_set(kind, override["set"], where)
        variants.append(VariantSpec(variant_id, label, tuple(assumptions), tuple(overrides)))
    if not variants:
        raise SimulationError("whatifs: at least one variant is required")
    return simulation_id, variants


def _apply_to_provenance(reported, changes: dict):
    provenance_changes = {k: v for k, v in changes.items() if k in _PROVENANCE_FIELDS}
    if provenance_changes:
        reported = replace(reported, provenance=replace(reported.provenance, **provenance_changes))
    return reported


def apply_overrides(scenario: Scenario, spec: VariantSpec) -> Scenario:
    requests = list(scenario.requests)
    resources = list(scenario.resources)
    shelters = list(scenario.shelters)
    routes = list(scenario.routes)
    where = f"variant '{spec.variant_id}'"

    for override in spec.overrides:
        kind = override["kind"]
        changes = override["set"]
        entity_changes = {k: v for k, v in changes.items() if k not in _PROVENANCE_FIELDS}
        if kind == "route":
            matches = [i for i, r in enumerate(routes)
                       if r.route.origin == override["origin"] and r.route.destination == override["destination"]]
            if not matches:
                raise SimulationError(
                    f"{where}: no route {override['origin']}->{override['destination']} in scenario")
            for i in matches:
                reported = routes[i]
                if entity_changes:
                    reported = replace(reported, route=replace(reported.route, **entity_changes))
                routes[i] = _apply_to_provenance(reported, changes)
        else:
            pools = {"request": requests, "resource": resources, "shelter": shelters}
            keys = {
                "request": lambda r: r.request.request_id,
                "resource": lambda r: r.resource.resource_id,
                "shelter": lambda r: r.shelter.shelter_id,
            }
            inner = {"request": "request", "resource": "resource", "shelter": "shelter"}
            pool = pools[kind]
            index = next((i for i, item in enumerate(pool) if keys[kind](item) == override["id"]), None)
            if index is None:
                raise SimulationError(f"{where}: no {kind} '{override['id']}' in scenario")
            reported = pool[index]
            if entity_changes:
                reported = replace(reported, **{inner[kind]: replace(getattr(reported, inner[kind]), **entity_changes)})
            pool[index] = _apply_to_provenance(reported, changes)

    return replace(scenario, requests=tuple(requests), resources=tuple(resources),
                   shelters=tuple(shelters), routes=tuple(routes))


def _snapshot(proposal: DispatchProposal) -> dict:
    return {
        "status": proposal.status,
        "resource_id": proposal.resource_id,
        "shelter_id": proposal.shelter_id,
        "eta_minutes": proposal.eta_minutes,
    }


def _diff(base: list[DispatchProposal], variant: list[DispatchProposal]) -> list[dict]:
    base_by_id = {p.request_id: p for p in base}
    result = []
    for proposal in sorted(variant, key=lambda p: p.request_id):
        before = _snapshot(base_by_id[proposal.request_id])
        after = _snapshot(proposal)
        result.append({
            "request_id": proposal.request_id,
            "changed": before != after,
            "base": before,
            "variant": after,
        })
    return result


def simulate_payload(scenario: Scenario, simulation_id: str, variants: list[VariantSpec],
                     reference_time: str | None = None) -> dict:
    base_scenario, base_findings = validate_scenario(scenario, reference_time)
    base_proposals = plan_scenario(base_scenario)

    variant_results = []
    for spec in variants:
        overridden = apply_overrides(scenario, spec)
        corroborated, findings = validate_scenario(overridden, reference_time)
        proposals = plan_scenario(corroborated)
        variant_results.append({
            "variant_id": spec.variant_id,
            "label": spec.label,
            "assumptions": list(spec.assumptions),
            "overrides": [dict(o) for o in spec.overrides],
            "validation_findings": [f.as_dict() for f in findings],
            "diff": _diff(base_proposals, proposals),
        })

    return {
        "simulation_version": SIMULATION_VERSION,
        "simulation_id": simulation_id,
        "scenario_id": scenario.scenario_id,
        "reference_time": reference_time,
        "limitations": list(LIMITATIONS),
        "base": {
            "validation_findings": [f.as_dict() for f in base_findings],
            "proposals": [{"request_id": p.request_id, **_snapshot(p)} for p in base_proposals],
        },
        "variants": variant_results,
    }


def load_whatifs(path: str | Path) -> tuple[str, list[VariantSpec]]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SimulationError(f"whatifs: invalid JSON ({error})") from error
    return parse_whatifs(raw)
