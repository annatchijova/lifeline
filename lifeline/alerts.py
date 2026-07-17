"""Deterministic attention feed derived from immutable incident events.

Alerts are operational visibility, not dispatch authority. They are derived
solely from the event ledger and can be polled by a future desktop, mobile, or
notification adapter without giving that adapter planning authority.
"""

from __future__ import annotations

from hashlib import sha256


def _report(event: dict) -> dict | None:
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return None
    if event.get("event_type") == "report_added":
        return payload
    if event.get("event_type") == "report_superseded":
        replacement = payload.get("replacement")
        return replacement if isinstance(replacement, dict) else None
    return None


def _alert(event: dict, code: str, severity: str, detail: str) -> dict:
    token = f"{event['event_hash']}|{code}".encode("utf-8")
    return {
        "alert_id": sha256(token).hexdigest(),
        "revision": event["revision"],
        "event_hash": event["event_hash"],
        "entity_type": event["entity_type"],
        "entity_id": event["entity_id"],
        "code": code,
        "severity": severity,
        "detail": detail,
        "submitted_at": event["submitted_at"],
        "dispatch_authority": "none",
    }


def alerts_from_events(events: list[dict]) -> list[dict]:
    """Produce stable, non-authoritative attention signals from ledger events."""
    alerts: list[dict] = []
    for event in events:
        if event.get("event_type") == "report_superseded":
            alerts.append(_alert(
                event, "REPORT_SUPERSEDED", "info",
                "A later report superseded this entity's current operational snapshot.",
            ))
        report = _report(event)
        if report is None:
            continue
        entity_type = event["entity_type"]
        verification = report.get("verification_state")
        freshness = report.get("freshness")
        if verification != "verified" or freshness == "low":
            alerts.append(_alert(
                event, "EVIDENCE_REQUIRES_REVIEW", "review",
                "This report is not verified and fresh enough to support deterministic planning.",
            ))
        if entity_type == "request" and isinstance(report.get("urgency"), int) and report["urgency"] >= 4:
            alerts.append(_alert(
                event, "DECLARED_HIGH_URGENCY", "attention",
                f"A report declared urgency {report['urgency']}/5; human verification remains required.",
            ))
        elif entity_type == "resource" and report.get("available") is False:
            alerts.append(_alert(event, "RESOURCE_UNAVAILABLE", "attention", "A resource was marked unavailable."))
        elif entity_type == "shelter" and (report.get("open") is False or report.get("beds_open") == 0):
            alerts.append(_alert(event, "SHELTER_CAPACITY_UNAVAILABLE", "attention", "A shelter was marked closed or reported no open beds."))
        elif entity_type == "route" and report.get("open") is False:
            alerts.append(_alert(event, "ROUTE_CLOSED", "attention", "A route was marked closed."))
    return alerts
