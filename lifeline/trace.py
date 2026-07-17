"""Optional CRONOS trace of each planning run.

CRONOS is an optional component: if it cannot be imported, planning and
export proceed unchanged and the absence is reported once on stderr. The
trace records what the kernel did; it never influences any sealed value.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from lifeline.core import DispatchProposal
from lifeline.scenario import Scenario

CRONOS_PATH_VAR = "LIFELINE_CRONOS_PATH"
DEFAULT_CRONOS_PATH = "/home/labestiadevigia/cronos"


def record_trace(out_dir: str | Path, scenario: Scenario, proposals: list[DispatchProposal], seal: dict) -> bool:
    """Record one planning run; return True if a trace was written."""
    cronos_path = os.environ.get(CRONOS_PATH_VAR, DEFAULT_CRONOS_PATH)
    if cronos_path and cronos_path not in sys.path and Path(cronos_path).is_dir():
        sys.path.insert(0, cronos_path)
    try:
        from fractions import Fraction

        from cronos.store import TraceStore
        from cronos.tracer import CronosTracer
    except ImportError:
        print("cronos not available: planning trace skipped (plan and seal are unaffected)", file=sys.stderr)
        return False

    store = TraceStore(str(Path(out_dir) / "trace.sqlite"))
    tracer = CronosTracer(
        store,
        agent_id="lifeline-kernel",
        channel_id="incident-room",
        user_id="cli",
        objective=f"plan scenario {scenario.scenario_id}",
    )
    proposed = sum(1 for p in proposals if p.status == "PROPOSED")
    with tracer:
        tracer.add_evidence(f"scenario sha256={seal['scenario_sha256']}")
        tracer.call_tool(
            "plan_scenario",
            f"{len(proposals)} outcomes: {proposed} PROPOSED, {len(proposals) - proposed} NEEDS_HUMAN_REVIEW",
        )
        for proposal in proposals:
            if proposal.status != "PROPOSED":
                tracer.add_evidence(
                    f"{proposal.request_id} needs human review: {'; '.join(proposal.reasons)}")
        tracer.decide(
            f"sealed plan sha256={seal['sha256']} awaiting human approval",
            Fraction(1),
        )
    return True
