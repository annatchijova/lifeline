# LIFELINE — Judges' Submission Guide

This document is the working surface for hackathon submission answers, judge
briefings, application forms, and short-form project descriptions. It points
back to the repository's technical evidence so that the pitch stays aligned
with what the code actually does.

## One-line description

LIFELINE is a human-led incident coordination operating system that turns
partial, stale, and contradictory operational reports into inspectable plans,
explicit evidence gaps, human approvals, and independently verifiable audit
artifacts.

## Origin story

The project began as a deliberate change of direction. Its creator usually
uses ChatGPT to think through forensic and legal systems, where provenance,
contradictory accounts, auditability, and human responsibility are central.
She challenged the collaboration to build something genuinely different from
that work: a serious emergency-coordination system, not a renamed forensic
tool and not merely a beautiful demo.

The idea was developed iteratively: first the human-accountability boundary,
then the evidence and verification model, then the incident lifecycle, and
finally a synthetic scenario serious enough to expose hard cases rather than
just produce a polished screen.

The system was built in Codex on Linux with ChatGPT 5.6 Terra and Luna. Those
names describe the working agents used during the build; the repository is the
source of truth. Design claims are backed by code, tests, generated artifacts,
and adversarial review rather than by the conversation alone.

## The problem

During an emergency, the problem is often not the absence of information but
the absence of a shared, trustworthy picture. Reports arrive from radios,
operators, sensors, public channels, and spreadsheets. They may disagree, go
stale, or omit the evidence needed to act. A system that silently averages
these reports can create false confidence; a system that hides uncertainty
makes human accountability impossible.

## The solution

LIFELINE keeps the operational lifecycle visible:

```text
evidence → validation → briefing → incident revision
         → planning → simulation → human approval
         → audit trail → export → offline verification
```

The deterministic kernel proposes only feasible actions from corroborated
facts. It does not dispatch resources, rank the value of human lives, or
pretend that contradictory evidence is resolved. When a proposal is blocked,
the system exposes the reason and the evidence still required.

## What the demo proves

The synthetic demo is designed to show the complete path in a few minutes:

1. A flood incident is loaded into the incident room.
2. The briefing shows requests, resources, constraints, and warnings.
3. Validators expose stale, unverified, and contradictory reports.
4. The Verification Graph shows supporting evidence, refuting evidence, and
   unresolved artifacts.
5. The planning kernel produces proposals and human-review states.
6. A changed route or capacity report creates a new incident revision instead
   of editing history.
7. Alternative scenarios show how a changed world changes the plan.
8. A local authenticated coordinator approves or rejects a proposal.
9. The approval ledger records the human decision.
10. The CLI verifies the plan, seals, incident ledger, and approval chain.
11. Optional Agent Briefing Mode uses OpenAI to narrate only the sealed,
    cited evidence packet; it cannot alter the plan or make the decision.

All data in the demo is synthetic. The project has not been used in real
incidents and is not a live emergency service.

## Why this is different

- **Uncertainty is a product feature.** Contradictions and missing evidence
  remain visible instead of being compressed into a confidence score.
- **The machine proposes; a person decides.** Approval is explicit and
  authenticated. Nothing is dispatched by the software.
- **The past is preserved.** Corrections create revisions and ledger events;
  reports are not silently edited or deleted.
- **Verification is independent.** Hash seals protect integrity, while
  semantic verification checks coverage, state coherence, allowed actions,
  bindings, and duplicate decisions.
- **The output is portable.** Plans, GeoJSON, verification artifacts, traces,
  and ledgers can be exported and checked offline.
- **OpenAI is interpretive, not authoritative.** Agent Briefing Mode turns a
  sealed evidence packet into cited natural language without giving the model
  tools for planning, approval, incident mutation, alerting, or dispatch.

## Technical evidence

| Capability | Evidence |
|---|---|
| Incident backend and revisions | [`lifeline/incidents.py`](../lifeline/incidents.py) |
| Role-based local authentication | [`lifeline/auth.py`](../lifeline/auth.py) |
| Deterministic planning kernel | [`lifeline/core.py`](../lifeline/core.py) |
| Evidence validators | [`lifeline/validators.py`](../lifeline/validators.py) |
| Human briefing | [`lifeline/briefing.py`](../lifeline/briefing.py) |
| Alerts and attention feed | [`lifeline/alerts.py`](../lifeline/alerts.py) |
| Alternative scenarios | [`lifeline/simulate.py`](../lifeline/simulate.py) |
| Approval ledger | [`lifeline/approvals.py`](../lifeline/approvals.py) |
| Verification artifact | [`lifeline/verification.py`](../lifeline/verification.py) |
| Export and GeoJSON | [`lifeline/export.py`](../lifeline/export.py) |
| CRONOS-compatible trace | [`lifeline/trace.py`](../lifeline/trace.py) |
| Live incident room | [`web/room.html`](../web/room.html) |
| Operations console | [`web/ops.html`](../web/ops.html) |
| Offline verification CLI | [`lifeline/__main__.py`](../lifeline/__main__.py) |
| Optional OpenAI agent narration | [`lifeline/agent.py`](../lifeline/agent.py) |
| Adversarial security review | [`docs/RED_TEAM_AUDIT_2026-07-19.md`](RED_TEAM_AUDIT_2026-07-19.md) |

## Suggested answers to common judge questions

### Does LIFELINE make emergency decisions?

No. It deterministically checks constraints and produces inspectable
proposals. A human coordinator must approve them. The system has no dispatch
authority and does not send alerts to external channels.

### Why not use an LLM to decide?

Because a fluent answer is not evidence. LIFELINE separates deterministic
fact handling and access control from optional future narration. A language
model may explain selected evidence, but it must not select, reorder, invent,
or authorize operational facts. The optional OpenAI Agent Briefing Mode uses a
sealed read-only packet, strict structured output, supplied citations, and no
mutation tools. See [`docs/AGENT_BRIEFING_MODE.md`](AGENT_BRIEFING_MODE.md).

### Is the data real?

No. The included flood scenario is synthetic and deliberately contains
non-obvious, stale, unverified, and contradictory reports. The project has not
been used in real incidents.

### What happens when reports conflict?

The conflict is preserved and surfaced. The affected proposal is downgraded or
blocked, and the artifact states what discriminating evidence or human review
is required. The system does not average contradictory reports into false
certainty.

### What does the cryptographic seal prove?

It proves the exported bytes and their declared bindings were not changed
after sealing. Semantic verification adds structural checks. Neither mechanism
proves that the original report was true; that remains a human and operational
responsibility.

### Is this production-ready?

No. It is a research and hackathon prototype with a carefully tested core and
adversarial security work. Live deployment would require field validation,
identity governance, accessibility review, resilience testing, and acceptance
by the responsible organization.

## Judge-facing links

- [`README.md`](../README.md) — product framing, use cases, architecture, and
  safety boundary.
- [`docs/DEMO_VIDEO_SCRIPT_180S.md`](DEMO_VIDEO_SCRIPT_180S.md) — timed demo
  script and screen plan.
- [`docs/LIFELINE_OS_EN.md`](LIFELINE_OS_EN.md) — extended product and
  architecture framing.
- [`docs/VERIFICATION_ARTIFACT.md`](VERIFICATION_ARTIFACT.md) — verification
  contract and semantic guarantees.
- [`docs/AGENT_BRIEFING_MODE.md`](AGENT_BRIEFING_MODE.md) — optional OpenAI
  narration contract, input boundary, and verification limits.
- [`docs/EXPORT_RECOVERY.md`](EXPORT_RECOVERY.md) — export atomicity and
  recovery boundary.
- [`docs/RED_TEAM_AUDIT_2026-07-19.md`](RED_TEAM_AUDIT_2026-07-19.md) and
  [`docs/RED_TEAM_FOLLOWUP_2026-07-20.md`](RED_TEAM_FOLLOWUP_2026-07-20.md) —
  adversarial findings, fixes, and verification evidence.
- [`SECURITY.md`](../SECURITY.md) — current security scope and limitations.

## Submission checklist

- [ ] Confirm the submission states that all demo data is synthetic.
- [ ] Confirm the submission states that LIFELINE has not been used in real
      incidents.
- [ ] Link the 3–4 minute demo video.
- [ ] Show one contradiction, one revision, one blocked proposal, one human
      approval, and one offline verification result.
- [ ] Do not describe a proposal as a dispatch or imply that the system sends
      responders.
- [ ] Run `python3 -m pytest -q` before submitting.
- [ ] Run `python3 -m lifeline verify --out out` and retain the output.
