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

## View the incident room

```bash
cd web
python3 -m http.server 8788 --bind 127.0.0.1
```

Open `http://127.0.0.1:8788`.

## Roadmap

1. Signed/validated incident ingestion and human verification workflows.
2. Real routing adapters with explicit freshness and source metadata.
3. Per-organization roles, approvals, and offline synchronization.
4. Optional model narration outside the planning authority boundary.

See [LIFELINE OS (English)](docs/LIFELINE_OS_EN.md) and
[LIFELINE OS (Español)](docs/LIFELINE_OS.md) for the product architecture,
ethical boundaries, simulation model, and the research patterns that inform it.
