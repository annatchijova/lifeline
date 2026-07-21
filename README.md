# LIFELINE

### When the water rises, the first enemy is not the flood. It is the fog.

In the opening hours of a disaster, people are rarely lost for lack of boats or
beds. They are lost for lack of a shared picture. Which family called. Which
road is still open. Which shelter still has room. Which boat already left, and
where it went. The facts exist — scattered across radios, spreadsheets, and the
memory of exhausted people. No one can see them whole, in time.

The tempting fix is to hand the whole mess to an algorithm and let it decide who
gets rescued first. **LIFELINE refuses to do that — on purpose.**

LIFELINE is open infrastructure for humanitarian coordination that makes the
truth *inspectable* and leaves the decision with a human. It turns verified
operational facts — requests for help, available resources, open routes, shelter
capacity — into a transparent, reproducible dispatch **proposal**. Then it
stops. It never sends a responder. It never ranks whose life matters more. It
never claims to predict who survives. A coordinator makes every call and carries
every consequence — but now they can see the whole board while they do.

Because when a machine gets a disaster decision wrong, *"the algorithm chose"* is
not an answer anyone can live with. So LIFELINE is built the other way around: a
person is always the one who chooses, every fact behind that choice has a
source, every proposal waits for a human yes, and every action is sealed into an
audit trail that cannot be quietly rewritten.

> **The map is not the decision. The person is.**

## LIFELINE OS

LIFELINE is not only a planner and it is not an autonomous dispatch system. It
is a local, human-led operating system for coordinating an incident from the
first report to the final verification:

```text
incoming evidence
      ↓
briefing → deterministic validators → alerts
      ↓                         ↓
incident revisions       verification graph
      ↓                         ↓
planning kernel → simulations / alternatives
      ↓
human approval → audit ledger → export + offline verification
```

## Why this project exists

LIFELINE grew out of a deliberate challenge. Its creator usually uses ChatGPT
to think through forensic and legal systems, where provenance, contradictory
accounts, auditability, and human responsibility are central. She asked
ChatGPT for ten directions that would force her out of that domain; three of
them felt worth pursuing and were combined into one question: how can an
emergency-coordination system make uncertainty visible without handing a life
and safety decision to an algorithm?

The idea was developed by asking what could make incomplete, contradictory,
time-sensitive information useful without pretending that an algorithm should
decide whose life matters more. That inquiry became LIFELINE's evidence model,
incident revisions, simulations, human approvals, and verification artifacts.

The project was built iteratively in Codex on Linux by Anna Tchijova with
ChatGPT 5.6 Terra and Luna: define a boundary, close one module, test and
audit it, then compose the next. The optional Agent Briefing Mode is one
example—it was added after the deterministic lifecycle existed and was
constrained to select opaque citations rather than acquire decision authority.
The repository, tests, generated artifacts, and adversarial audits are the
source of truth for what the system does. The project uses synthetic data and
has not been used in real incidents. See
[`docs/CODEX_COLLABORATION.md`](docs/CODEX_COLLABORATION.md) for the division
of responsibility and review method.

The product surface includes an incident backend, local authenticated
coordinators, typed report ingestion, role boundaries, a live operations room,
human briefing, deterministic planning, alternative-scenario simulation,
approval recording, alert feeds, GeoJSON export, CRONOS-compatible tracing,
sealed verification artifacts, and a verification CLI. The static judge demo
is only the visible window into that larger lifecycle.

## Repository at a glance

LIFELINE is a working open-source research prototype, not a concept paper or
an interface mock-up. The current tracked baseline contains **10,051 lines of
code across 61 versioned files**, including **5,380 lines of Python code**,
2,363 lines of Markdown, 1,177 lines of JSON, and 1,131 lines of HTML. It also
has **more than 100 automated regression tests** across a deterministic
planning kernel, authenticated local incident backend, simulation engine,
sealed verification artifacts, CLI tooling, and browser operations surfaces.

| Tracked surface (`cloc`) | Files | Code lines |
| --- | ---: | ---: |
| Python | 32 | 5,380 |
| Markdown | 18 | 2,363 |
| JSON | 8 | 1,177 |
| HTML | 3 | 1,131 |
| **Total** | **61** | **10,051** |

```text
lifeline/
├── lifeline/
│   ├── __main__.py        # CLI: plan, verify, serve, operator, narrate
│   ├── alerts.py          # deterministic attention feed
│   ├── briefing.py        # human-readable incident briefing
│   ├── core.py            # deterministic planning kernel
│   ├── validators.py      # freshness, contradiction, and input gates
│   ├── verification.py    # sealed Verification Graph
│   ├── incidents.py       # append-only incident revisions
│   ├── approvals.py       # human decision ledger
│   ├── auth.py            # local operator roles
│   ├── simulate.py        # explicit alternative scenarios
│   ├── agent.py           # optional non-authoritative reading guide
│   ├── export.py          # plan, GeoJSON, and seal artifacts
│   ├── trace.py           # CRONOS-compatible event trace
│   └── server.py          # loopback incident-room backend
├── web/
│   ├── index.html         # static bilingual judge landing page
│   ├── room.html          # synthetic incident map room
│   ├── ops.html           # authenticated operations console
│   └── demo/              # sealed static synthetic demo bundle
├── scenarios/
│   ├── flood_v1.json      # base synthetic flood incident
│   └── flood_v1_whatifs.json # alternative conditions for simulation
├── tests/                 # regression, security, and adversarial coverage
├── docs/                  # architecture, audits, validation, and video runbook
├── tools/                 # reproducible demo-bundle tooling
├── HACKATHON.MD           # judge links and end-to-end runbook
└── README.md
```

The implementation is substantial without claiming operational maturity. See
[`docs/PROTOTYPE_STATUS.md`](docs/PROTOTYPE_STATUS.md) for the evidence,
limits, red-team scope, and next validation steps.

## What it is useful for

LIFELINE is designed for situations where many people must coordinate from
partial, stale, or contradictory information and still be able to explain
what happened later. Example use cases include:

- **Flood response:** compare evacuation requests, boats, shelters, and route
  reports without silently treating a rumor as a fact.
- **Wildfire or storm coordination:** maintain incident revisions as roads,
  resources, and shelter capacity change during an operation.
- **Search-and-rescue staging:** expose feasible resource/request pairings while
  leaving prioritization and dispatch authority with the coordinator.
- **Humanitarian logistics:** record why a delivery, transfer, or shelter
  proposal is blocked when a route, capacity claim, or source is not verified.
- **Training and tabletop exercises:** run synthetic alternatives, inspect the
  evidence graph, rehearse approvals, and export a reproducible incident record.

In every case, the system answers: *what was reported, what was corroborated,
what conflicts, what is missing, what could be proposed, and who approved it?*
It does not answer: *which human life is worth more?*

## Prototype status, evidence, and safety boundary

LIFELINE is a fully functional **research and hackathon prototype** with a
synthetic end-to-end scenario: report ingestion, deterministic validation,
incident revisions, planning, simulation, human approval, export, offline
verification, and an optional cited reading guide have all been exercised
locally. Focused red-team rounds reproduced and fixed security issues in
approval concurrency, bootstrap races, artifact/static-file boundaries, HTTP
request handling, and the optional agent boundary. Their methods, findings,
fixes, and falsified vectors are published in [`docs/`](docs/).

That evidence has clear limits. LIFELINE has **not been used in real
incidents**, is not field-validated, and does not claim to be production-ready
or safe for live emergency operations. The included flood scenario, reports,
identities, routes, capacities, and decisions are synthetic. They demonstrate
architecture and failure modes; they do not represent real people or current
field conditions. The red-team work is focused security hardening, not an
exhaustive invariant, resilience, accessibility, or organizational-governance
assessment.

The next research steps are broader synthetic and adversarial scenario
campaigns, deeper invariant and recovery testing, operator-centered review,
and only then carefully governed evaluation with appropriately authorized real
incident data. Any future deployment would also require identity governance,
accessibility and language review, resilience testing, local protocol design,
and formal acceptance by the responsible organization.

Read the evidence directly: [`Prototype Status and Validation Roadmap`](docs/PROTOTYPE_STATUS.md),
[`Verification Artifact`](docs/VERIFICATION_ARTIFACT.md),
[`Agent Briefing Mode`](docs/AGENT_BRIEFING_MODE.md), and the published
[`red-team audits`](docs/RED_TEAM_AUDIT_2026-07-19.md).

This repository must not replace official emergency services, an incident
command system, professional advice, or local operational procedures.

## Three commitments — written into the code, not just the pitch

- **Facts have sources.** A request, resource, route, or shelter must be
  verified and fresh before it can shape a plan. Contradictions are downgraded,
  never averaged away. LIFELINE would rather say *"I can't corroborate this"*
  than proceed on a guess.
- **Feasible is explicit.** Capacity, route status, availability, medical
  compatibility — hard constraints checked deterministically, not a model's
  hunch. When a rescue can't be proposed, LIFELINE says exactly why.
- **People stay accountable.** Every proposed action waits for an authorized
  human, and every decision is written into a hash-chained, tamper-evident
  ledger. You can always answer *who decided, on what evidence, and when.*

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

An optional language model may select opaque evidence references for a
completed, verified plan. LIFELINE renders every visible sentence locally from
the sealed packet and fixed templates; the provider cannot supply resource
names, routes, requests, advice, or operational instructions as prose.

## Optional Agent Briefing Mode

For the OpenAI hackathon, LIFELINE includes an optional OpenAI interpretation
layer. `lifeline narrate --out out` first verifies the completed plan and
Verification Graph locally, then sends a closed, read-only packet to the
Responses API. The provider returns only a structured selection of supplied
opaque citation IDs with `INTERPRETIVE_ONLY`; LIFELINE renders the human-facing
briefing locally and seals it with the plan and verification hashes.

The agent is intentionally not an operational tool. It has no incident-write,
planning, approval, alert, or dispatch capability. It cannot introduce prose
into the briefing, choose a resource, or make a decision; it only selects
sealed references for a locally rendered reading guide. The room displays that
guide only when its seal and input bindings hold, and the deterministic system
remains fully usable when no API key or briefing is available. A local
coordinator can also request the same cited briefing for a
current incident through the Operations console; that optional provider egress
is authenticated and cannot alter the incident. See
[`docs/AGENT_BRIEFING_MODE.md`](docs/AGENT_BRIEFING_MODE.md) for the contract,
local setup, and verification boundary.

| Step | OpenAI can do | LIFELINE still controls |
| --- | --- | --- |
| Before egress | Nothing | Verifies the plan, verification graph, and their seals locally. |
| Provider call | Select opaque citation IDs from the closed packet. | Keeps raw report strings, credentials, write endpoints, and operational tools out of the request. |
| Display | Nothing beyond its citation selection. | Renders every human-visible sentence from sealed values and fixed templates. |
| Decision path | Nothing | Deterministic feasibility, human approval, audit ledger, and offline verification. |

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

For hackathon applications and judge questions, see the
[`Judges' Submission Guide`](docs/JUDGES_SUBMISSION.md). It collects the
problem statement, product framing, demo claims, technical evidence, common
answers, and the explicit boundary that the project uses synthetic data and
has not been used in real incidents. The deeper architecture, verification,
export, and adversarial-audit documents are linked there as well. The
[`Hackathon Runbook`](HACKATHON.MD) records the public judge URLs, submission
references, and the exact local end-to-end walkthrough.

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
`out/plan.json` (sealed decision artifact, no floats),
`out/plan.seal.json` (SHA-256 digest and scenario digest), and
`out/verification.json` (the non-authoritative, sealed evidence-gap artifact
bound to that exact plan). If CRONOS is
available locally, each run also records a planning trace in
`out/trace.sqlite`; its absence only skips the trace.
Each artifact is published atomically within the output directory; an
interrupted multi-file re-export remains detectable by its seals and cannot
record an approval. See [the export recovery boundary](docs/EXPORT_RECOVERY.md).

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

This recomputes the plan and verification seals, checks their binding, checks the approvals chain, and—when local
incidents exist—checks every incident snapshot against the tip of its
hash-linked event ledger. Altered, inserted, reordered, or dropped interior
entries fail verification. Tail truncation is only detectable once an external
anchor exists (roadmap).

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

Plans produced from a persisted incident have their own approval ledger. The
plan includes the incident revision and scenario digest inside its seal; a
coordinator can only record a decision against that exact plan. If a report,
correction, or reference time changes, the old plan hash is rejected as stale.
The persisted-plan endpoint returns the same non-authoritative verification
artifact and independent seal as the CLI export, bound to that exact incident
revision and plan hash.

```bash
curl -X POST http://127.0.0.1:8788/api/incidents/flood-v1-synthetic/approvals \
  -H "Authorization: Bearer $LIFELINE_TOKEN" -H 'Content-Type: application/json' \
  -d '{"request_id":"family-north","action":"approve","proposal_audit_hash":"…","plan_sha256":"…","reference_time":"2026-07-17T11:00:00Z"}'
curl -H "Authorization: Bearer $LIFELINE_TOKEN" \
  'http://127.0.0.1:8788/api/incidents/flood-v1-synthetic/approvals'
```

The second endpoint exposes the per-incident hash chain. It records a human
decision; it never dispatches a resource.

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
4. Agent-briefing evaluation corpus, language review, and operator testing
   before any use beyond synthetic exercises.

See [LIFELINE OS (English)](docs/LIFELINE_OS_EN.md),
[LIFELINE OS (Español)](docs/LIFELINE_OS.md), and the
[verification artifact contract](docs/VERIFICATION_ARTIFACT.md) for the
product architecture, ethical boundaries, simulation model, and the research
patterns that inform it.
