from lifeline.briefing import incident_briefing
from lifeline.core import DispatchProposal
from lifeline.validators import Finding


def test_briefing_is_complete_and_never_a_priority_score():
    proposed = DispatchProposal(
        "request-a", "PROPOSED", "resource-a", "shelter-a", 12,
        ("urgency=5", "human approval required"), "a" * 64,
    )
    review = DispatchProposal(
        "request-b", "NEEDS_HUMAN_REVIEW", None, None, None,
        ("urgency=4", "unverified report"), "b" * 64,
    )
    finding = Finding("STALE_REPORT", "warn", "route", "a->b", "downgraded")

    briefing = incident_briefing([proposed, review], [finding])

    assert briefing["proposal_counts"] == {
        "proposed": 1, "needs_human_review": 1, "total": 2,
    }
    assert briefing["review_queue"] == [{
        "request_id": "request-b", "reasons": ["urgency=4", "unverified report"],
        "audit_hash": "b" * 64,
    }]
    assert briefing["validation"] == {
        "warn": 1, "info": 0, "by_code": [{"code": "STALE_REPORT", "count": 1}],
    }
    assert all("priority score" not in key for key in briefing)
