"""Deterministic incident-room read model derived from a sealed plan.

This module does not rank people, resources, findings, or alternatives.  It
only makes the already-sealed state legible at a glance so a coordinator can
see the complete review queue and every validation finding before opening a
proposal.  The result is included inside plan.json, rather than emitted as an
independent authority-bearing artifact.
"""

from __future__ import annotations

from collections import Counter

from lifeline.core import DispatchProposal
from lifeline.validators import Finding

BRIEFING_VERSION = 1


def incident_briefing(
    proposals: list[DispatchProposal],
    findings: tuple[Finding, ...] | list[Finding] = (),
) -> dict:
    """Return a canonical, complete summary of a plan's review surface.

    Proposal order is preserved from the planner.  Findings are already
    deterministically ordered by the validator; their entity references remain
    visible here rather than being collapsed into an opaque score.
    """
    status_counts = Counter(proposal.status for proposal in proposals)
    severity_counts = Counter(finding.severity for finding in findings)
    code_counts = Counter(finding.code for finding in findings)
    review_queue = [
        {
            "request_id": proposal.request_id,
            "reasons": list(proposal.reasons),
            "audit_hash": proposal.audit_hash,
        }
        for proposal in proposals
        if proposal.status == "NEEDS_HUMAN_REVIEW"
    ]
    return {
        "briefing_version": BRIEFING_VERSION,
        "proposal_counts": {
            "proposed": status_counts["PROPOSED"],
            "needs_human_review": status_counts["NEEDS_HUMAN_REVIEW"],
            "total": len(proposals),
        },
        "review_queue": review_queue,
        "validation": {
            "warn": severity_counts["warn"],
            "info": severity_counts["info"],
            "by_code": [
                {"code": code, "count": code_counts[code]}
                for code in sorted(code_counts)
            ],
        },
        "limitations": [
            "This is a complete read model of the sealed plan, not a priority score or dispatch authority.",
            "Every proposal still requires an authorized human decision.",
        ],
    }
