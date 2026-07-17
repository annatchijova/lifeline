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

The deterministic core selects only eligible *proposals*: verified,
non-stale available resource; verified, non-stale open route; compatible
capability; and verified, non-stale remaining capacity at the request's
declared destination. It records why a request could not be proposed. It
never sends a dispatch.

An optional language model may eventually narrate a completed, human-approved
plan from its recorded evidence. It must not select, reorder, or invent
resources, routes, requests, or advice.

## Run checks

```bash
python3 -m pytest -q
```

Install the package locally to use the `lifeline` command from any directory:

```bash
python3 -m pip install -e .
lifeline plan scenarios/flood_v1.json --out out --reference-time 2026-07-17T11:00:00Z
```

LIFELINE is released under the [Apache License 2.0](LICENSE). See
[`CONTRIBUTING.md`](CONTRIBUTING.md) for the engineering contract and
[`SECURITY.md`](SECURITY.md) for the current prototype boundary. The governed
human-led, Codex-assisted development workflow is documented in
[`docs/CODEX_COLLABORATION.md`](docs/CODEX_COLLABORATION.md).

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
closed, non-verified, or stale (`low` freshness) routes, resources, or
shelters. Unparseable and future-dated timestamps are downgraded to `low`
freshness when a reference time is supplied, so they cannot quietly support a
proposal.

Open `http://127.0.0.1:8788/web/room.html?mode=live`. The live room renders only what the
kernel exported: `out/room.geojson` (display layer, floats allowed),
`out/plan.json` (sealed decision artifact, no floats), and
`out/plan.seal.json` (SHA-256 digest and scenario digest). If CRONOS is
available locally, each run also records a planning trace in
`out/trace.sqlite`; its absence only skips the trace.

The top of the room is a deterministic briefing embedded in the sealed plan:
it exposes the complete proposal/review counts and validation warnings without
ranking people or becoming a separate decision authority.

Approve/Reject decisions in the room are appended to
`out/approvals.jsonl`, a hash-chained, append-only log bound to the exact
plan seal and proposal audit hash (stale plans and duplicates are refused
with 409). The server binds to loopback and requires a local authenticated
coordinator token: the approver identity is derived from that token, not a
client-supplied name. Verify everything offline with:

```bash
python3 -m lifeline verify --out out
```

This recomputes the plan seal and checks the approvals chain; altered,
inserted, reordered, or dropped interior entries fail verification. Tail
truncation is only detectable once an external anchor exists (roadmap).

## Local incident backend

`lifeline serve` also runs a loopback-only incident backend. It persists its
SQLite state at `out/incidents.sqlite3`, which the static server deliberately
does **not** expose. The public judge demo never connects to this API.

With the local server running, open
`http://127.0.0.1:8788/web/ops.html` for a bilingual operations console. It
keeps the entered token only in the active tab and provides incident search,
schema-v1 scenario creation, typed report append/correction, sealed-plan
recomputation, and a 15-second polling attention feed. It is intentionally not
a public hosted console and does not send alerts to external channels.

Bootstrap the first local administrator once. The command displays a token
once; store it in your local secret manager rather than a shell history or the
repository. Other local roles can then be created by entering that token at a
terminal prompt.

```bash
lifeline operator init --out out --id anna-coordinator
lifeline operator add --out out --id field-reporter --role reporter
lifeline serve --out out
```

Use the token to call the API. `reader` can inspect incidents and feeds,
`reporter` can create incidents and append reports, and `coordinator` can
supersede a report and record an approval. `admin` can provision local roles.
These are local prototype credentials, not an organization identity system;
the backend must remain loopback-only until a deployment and identity design is
reviewed.

Create a validated incident from a schema-v1 scenario:

```bash
curl -X POST http://127.0.0.1:8788/api/incidents \
  -H "Authorization: Bearer $LIFELINE_TOKEN" \
  -H 'Content-Type: application/json' \
  --data-binary @scenarios/flood_v1.json
```

Search incidents, append a typed report, request a sealed plan, or poll the
append-only feed used by future alert clients:

```bash
curl -H "Authorization: Bearer $LIFELINE_TOKEN" 'http://127.0.0.1:8788/api/incidents?q=flood'
curl -X POST http://127.0.0.1:8788/api/incidents/flood-v1-synthetic/plan \
  -H "Authorization: Bearer $LIFELINE_TOKEN" -H 'Content-Type: application/json' \
  -d '{"reference_time":"2026-07-17T11:00:00Z"}'
curl -H "Authorization: Bearer $LIFELINE_TOKEN" 'http://127.0.0.1:8788/api/incidents/flood-v1-synthetic/events?after_revision=0'
curl -H "Authorization: Bearer $LIFELINE_TOKEN" 'http://127.0.0.1:8788/api/incidents/flood-v1-synthetic/alerts?after_revision=0'
```

The current ingestion API is append-only: report additions are validated
against the entire resulting scenario and create a hash-linked event revision.
Corrections use `POST /api/incidents/{id}/corrections` with the same
`entity_type`/`report` shape. They supersede the operational snapshot for the
next plan but preserve the previous report in a `report_superseded` ledger
event; there is no edit/delete endpoint and no silent mutation.

`/alerts` is the deterministic attention feed for polling clients. It flags,
for example, a closed route, unavailable resource, unverified evidence, or a
declared high-urgency report. Each alert explicitly carries
`dispatch_authority: "none"`: it tells people what changed, never what to do.
External channels (email, SMS, WhatsApp, pager) are intentionally not wired
until recipient identity, authorization, consent, and delivery failure policy
are defined.

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

The landing page and `http://127.0.0.1:8788/web/room.html` open a bundled,
sealed synthetic flood demo. Its approve/reject controls are interactive but
local to the browser: they never call the approvals API, write a chain entry,
or dispatch anything. Switch to `?mode=live` to inspect and approve the
export you generated. See `docs/adr/0001-map-stack.md` for the map stack
decision and the float boundary.

## Host the judge demo

`web/` is a self-contained static demo: it includes Leaflet, the sealed
synthetic plan, map layers, and simulated alternatives under `web/demo/`.
The included GitHub Pages workflow deploys that directory on every push to
`main` that changes the demo. In the repository's **Settings → Pages**, select
**GitHub Actions** once; after the first successful deployment, GitHub exposes
the public URL in the workflow's `github-pages` environment. The hosted demo
is deliberately demo-only: its approve/reject controls remain in-browser and
cannot write approval records or dispatch anything.

## Roadmap

1. Signed/validated incident ingestion and human verification workflows.
2. Real routing adapters with explicit freshness and source metadata.
3. Per-organization identity integration, approval policy, and offline synchronization.
4. Optional model narration outside the planning authority boundary.

See [LIFELINE OS (English)](docs/LIFELINE_OS_EN.md) and
[LIFELINE OS (Español)](docs/LIFELINE_OS.md) for the product architecture,
ethical boundaries, simulation model, and the research patterns that inform it.
