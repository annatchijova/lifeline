"""Deterministic corroboration validators.

Validators cross-check reported evidence before planning. They may only
DOWNGRADE a verification state (verified -> unverified/conflicting) or a
freshness level; upgrades require a human. Every change is recorded as a
finding, and findings are sealed with the plan so the downgrade itself is
auditable. No clock is read: staleness checks run only when an explicit
reference time is supplied, and their absence is reported as a finding
rather than silently skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from lifeline.scenario import Provenance, ReportedRequest, ReportedRoute, Scenario

STALE_MEDIUM_MINUTES = 90
STALE_LOW_MINUTES = 240
FRESHNESS_ORDER = {"high": 2, "medium": 1, "low": 0}


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str  # "info" or "warn"
    entity_type: str
    entity_id: str
    detail: str

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "detail": self.detail,
        }


def _parse_observed(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _age_minutes(observed_at: str, reference: datetime) -> int | None:
    observed = _parse_observed(observed_at)
    if observed is None or observed.tzinfo is None or reference.tzinfo is None:
        return None
    return int((reference - observed).total_seconds()) // 60


def _downgrade_state(provenance: Provenance, state: str) -> Provenance:
    return replace(provenance, verification_state=state)


def _check_route_contradictions(scenario: Scenario, findings: list[Finding]) -> tuple[ReportedRoute, ...]:
    groups: dict[tuple[str, str], list[ReportedRoute]] = {}
    for reported in scenario.routes:
        groups.setdefault((reported.route.origin, reported.route.destination), []).append(reported)

    updated: dict[int, ReportedRoute] = {}
    for (origin, destination), group in sorted(groups.items()):
        open_values = {reported.route.open for reported in group}
        if len(open_values) < 2:
            continue
        findings.append(Finding(
            "ROUTE_CONTRADICTION", "warn", "route", f"{origin}->{destination}",
            f"{len(group)} reports disagree on open state; all downgraded to conflicting",
        ))
        for reported in group:
            if reported.provenance.verification_state != "conflicting":
                updated[id(reported)] = replace(
                    reported, provenance=_downgrade_state(reported.provenance, "conflicting"))
    return tuple(updated.get(id(reported), reported) for reported in scenario.routes)


def _check_duplicate_requests(scenario: Scenario, findings: list[Finding]) -> tuple[ReportedRequest, ...]:
    groups: dict[tuple[str, str, int, bool], list[ReportedRequest]] = {}
    for reported in scenario.requests:
        request = reported.request
        key = (request.pickup_zone, request.destination_zone, request.people, request.medical_need)
        groups.setdefault(key, []).append(reported)

    updated: dict[str, ReportedRequest] = {}
    for key, group in sorted(groups.items()):
        if len(group) < 2:
            continue
        ordered = sorted(group, key=lambda item: (item.provenance.observed_at, item.request.request_id))
        first = ordered[0]
        for later in ordered[1:]:
            findings.append(Finding(
                "POSSIBLE_DUPLICATE", "warn", "request", later.request.request_id,
                f"same pickup, destination, people, and medical need as '{first.request.request_id}'; "
                "downgraded to unverified pending human confirmation",
            ))
            if later.provenance.verification_state == "verified":
                updated[later.request.request_id] = replace(
                    later, provenance=_downgrade_state(later.provenance, "unverified"))
    return tuple(updated.get(reported.request.request_id, reported) for reported in scenario.requests)


def _stale_level(age_minutes: int) -> str:
    if age_minutes > STALE_LOW_MINUTES:
        return "low"
    if age_minutes > STALE_MEDIUM_MINUTES:
        return "medium"
    return "high"


def _check_staleness(scenario: Scenario, reference_time: str | None, findings: list[Finding]) -> Scenario:
    if reference_time is None:
        findings.append(Finding(
            "STALENESS_UNCHECKED", "info", "scenario", scenario.scenario_id,
            "no reference time supplied; declared freshness was not corroborated",
        ))
        return scenario
    reference = _parse_observed(reference_time)
    if reference is None or reference.tzinfo is None:
        raise ValueError(f"reference time must be ISO 8601 with timezone, got {reference_time!r}")

    def refresh(entity_type: str, entity_id: str, provenance: Provenance) -> Provenance:
        age = _age_minutes(provenance.observed_at, reference)
        if age is None:
            findings.append(Finding(
                "UNPARSEABLE_TIMESTAMP", "warn", entity_type, entity_id,
                f"observed_at {provenance.observed_at!r} is not ISO 8601 with timezone; downgraded to 'low' freshness",
            ))
            return replace(provenance, freshness="low")
        if age < 0:
            findings.append(Finding(
                "FUTURE_TIMESTAMP", "warn", entity_type, entity_id,
                f"observed_at is {-age} minutes after the reference time; downgraded to 'low' freshness",
            ))
            return replace(provenance, freshness="low")
        computed = _stale_level(age)
        if FRESHNESS_ORDER[computed] < FRESHNESS_ORDER[provenance.freshness]:
            findings.append(Finding(
                "STALE_REPORT", "warn", entity_type, entity_id,
                f"declared freshness '{provenance.freshness}' but report is {age} minutes old; "
                f"downgraded to '{computed}'",
            ))
            return replace(provenance, freshness=computed)
        return provenance

    return replace(
        scenario,
        requests=tuple(replace(r, provenance=refresh("request", r.request.request_id, r.provenance)) for r in scenario.requests),
        resources=tuple(replace(r, provenance=refresh("resource", r.resource.resource_id, r.provenance)) for r in scenario.resources),
        shelters=tuple(replace(s, provenance=refresh("shelter", s.shelter.shelter_id, s.provenance)) for s in scenario.shelters),
        routes=tuple(replace(r, provenance=refresh("route", f"{r.route.origin}->{r.route.destination}", r.provenance)) for r in scenario.routes),
    )


def validate_scenario(scenario: Scenario, reference_time: str | None = None) -> tuple[Scenario, list[Finding]]:
    """Return the corroborated scenario and the findings that explain every change."""
    findings: list[Finding] = []
    scenario = replace(scenario, routes=_check_route_contradictions(scenario, findings))
    scenario = replace(scenario, requests=_check_duplicate_requests(scenario, findings))
    scenario = _check_staleness(scenario, reference_time, findings)
    findings.sort(key=lambda f: (f.code, f.entity_type, f.entity_id, f.detail))
    return scenario, findings
