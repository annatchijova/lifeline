# LIFELINE

**Open infrastructure for humanitarian coordination.**

LIFELINE is a decision-support system for incident coordinators. It turns
verified operational facts — requests for help, available resources, routes,
and shelter capacity — into a transparent proposed dispatch plan.

It does not autonomously dispatch responders, determine who is rescued, or
claim to predict survival. A human coordinator remains responsible for every
operational decision.

## First vertical slice

This repository starts with one deliberately small, testable flood-response
scenario:

- a deterministic planner with hard safety constraints;
- a SHA-256 append-only audit chain for planning events;
- a static bilingual incident room that shows the proposal and its evidence;
- no API key, cloud service, or model required.

The browser page contains illustrative data only. It is not a live emergency
service and must never be used as a substitute for official emergency systems.

## Safety boundary

The deterministic core selects only eligible *proposals*: available resource,
open route, compatible capability, and remaining shelter capacity. It records
why a request could not be proposed. It never sends a dispatch.

An optional language model may eventually narrate a completed, human-approved
plan from its recorded evidence. It must not select, reorder, or invent
resources, routes, requests, or advice.

## Run checks

```bash
python3 -m pytest -q
```

## Export a plan and run the incident room

```bash
python3 -m lifeline plan scenarios/flood_v1.json --out out --reference-time 2026-07-17T11:00:00Z
python3 -m lifeline serve --out out
```

Before planning, deterministic validators corroborate the declared evidence:
contradictory route reports are downgraded to `conflicting`, near-identical
requests are flagged as possible duplicates and downgraded to `unverified`,
and — only when an explicit `--reference-time` is supplied — declared
freshness is checked against report age and downgraded when stale. Validators
can only downgrade, never upgrade; every change is recorded as a finding
sealed inside `plan.json`. Without a reference time, staleness is reported as
unchecked rather than silently assumed fresh. Planning never relies on
closed, non-verified, or stale (`low` freshness) routes.

Open `http://127.0.0.1:8788/web/room.html`. The room renders only what the
kernel exported: `out/room.geojson` (display layer, floats allowed),
`out/plan.json` (sealed decision artifact, no floats), and
`out/plan.seal.json` (SHA-256 digest and scenario digest). If CRONOS is
available locally, each run also records a planning trace in
`out/trace.sqlite`; its absence only skips the trace.

Approve/Reject decisions in the room are appended to
`out/approvals.jsonl`, a hash-chained, append-only log bound to the exact
plan seal and proposal audit hash (stale plans and duplicates are refused
with 409). The server binds to loopback and has no authentication yet: the
approver identity is declared, not verified. Verify everything offline with:

```bash
python3 -m lifeline verify --out out
```

This recomputes the plan seal and checks the approvals chain; altered,
inserted, reordered, or dropped interior entries fail verification. Tail
truncation is only detectable once an external anchor exists (roadmap).

## Simulate alternatives

```bash
python3 -m lifeline simulate scenarios/flood_v1.json scenarios/flood_v1_whatifs.json \
  --out out --reference-time 2026-07-17T11:00:00Z
```

Variants are declared, explicit overlays on the base scenario ("north bridge
confirmed closed", "shelter loses beds"). Each variant is re-corroborated and
re-planned by the same deterministic pipeline, and `simulation.json` records
the per-request differences against the base plan, the assumptions, the
findings, and the model limitations — sealed in `simulation.seal.json` and
checked by `verify`. No score ranks the variants and no winner is chosen;
the room shows them as alternatives for a human to weigh. Simulated results
are never live facts.

The landing page remains at `http://127.0.0.1:8788/web/` with illustrative
content. See `docs/adr/0001-map-stack.md` for the map stack decision and the
float boundary.

## Roadmap

1. Signed/validated incident ingestion and human verification workflows.
2. Real routing adapters with explicit freshness and source metadata.
3. Per-organization roles, approvals, and offline synchronization.
4. Optional model narration outside the planning authority boundary.

See [LIFELINE OS (English)](docs/LIFELINE_OS_EN.md) and
[LIFELINE OS (Español)](docs/LIFELINE_OS.md) for the product architecture,
ethical boundaries, simulation model, and the research patterns that inform it.
