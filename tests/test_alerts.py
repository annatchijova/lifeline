from lifeline.alerts import alerts_from_events


def _event(entity_type, payload, *, event_type="report_added"):
    return {
        "revision": 2, "event_hash": "a" * 64, "entity_type": entity_type,
        "entity_id": "example", "event_type": event_type,
        "submitted_at": "2026-07-17T10:00:00Z", "payload": payload,
    }


def test_alerts_are_deterministic_and_have_no_dispatch_authority():
    event = _event("request", {
        "urgency": 5, "verification_state": "unverified", "freshness": "medium",
    })
    alerts = alerts_from_events([event])
    assert [alert["code"] for alert in alerts] == ["EVIDENCE_REQUIRES_REVIEW", "DECLARED_HIGH_URGENCY"]
    assert all(alert["dispatch_authority"] == "none" for alert in alerts)
    assert alerts == alerts_from_events([event])


def test_supersession_emits_a_visibility_alert_and_uses_the_replacement():
    event = _event("route", {
        "previous": {"open": True},
        "replacement": {"open": False, "verification_state": "verified", "freshness": "high"},
    }, event_type="report_superseded")
    assert [alert["code"] for alert in alerts_from_events([event])] == ["REPORT_SUPERSEDED", "ROUTE_CLOSED"]
