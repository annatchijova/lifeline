# Agent Briefing Mode

Agent Briefing Mode is LIFELINE's optional OpenAI interpretation layer. It
helps a human understand a completed incident state; it does not participate in
planning, approval, alert delivery, report ingestion, or dispatch.

## Authority boundary

```text
sealed plan + verification graph
              ↓
     verified read-only packet
              ↓
   optional OpenAI Responses call
              ↓
opaque citation reading guide
              ↓
local controlled-language renderer
              ↓
cited agent_briefing.json (separate seal)
              ↓
          human coordinator
```

The deterministic kernel remains authoritative for feasibility. The
Verification Graph remains authoritative for evidence gaps. The provider does
not return free-form narration: it may only select supplied opaque citation
IDs. LIFELINE sorts those selections into canonical packet order and renders
every displayed sentence locally from sealed typed values and fixed templates.

It cannot:

- create or alter incidents, reports, revisions, findings, plans, or
  simulations;
- change verification or freshness states;
- choose a resource, rank people, recommend a dispatch, or issue instructions
  through briefing prose (the provider has no prose field);
- approve or reject a proposal;
- send alerts or contact external channels;
- access operator tokens, approval ledgers, mutable incident state, or API
  write tools.

## Contract before the model is called

`lifeline narrate` first verifies all of the following locally:

1. `plan.json` matches `plan.seal.json`.
2. `verification.json` matches `verification.seal.json`.
3. The Verification Graph is bound to the same plan.
4. The Verification Graph passes its semantic, closed-vocabulary authority
   checks.

Only then does LIFELINE build a minimal packet containing typed proposal and
verification state, validation codes, and a closed list of opaque citation IDs.
The packet deliberately excludes raw mutable incident data, reporter-controlled
identifiers and provenance strings, operator credentials, approval records, and
all write endpoints. The local UI resolves an opaque citation back to the real
sealed evidence for the coordinator; the provider never needs those names.

For a persisted incident, the packet may also include a deterministic change
read model from the verified event ledger. Each change names its revision,
event type, entity class, and immutable event hash. Report payloads are reduced
to non-textual values and closed enums before they reach the model; source,
timestamp, zone, identifier, and other raw report content are not forwarded.
This lets the reading guide surface *what changed since a revision* without
treating an untrusted report string as instructions.

## OpenAI request policy

The implementation uses the OpenAI Responses API with:

- `store: false` (the request disables response storage; consult OpenAI's
  current data-controls documentation for the service-level retention policy);
- strict JSON Schema output;
- no OpenAI built-in tools;
- no custom function tools;
- an explicit `INTERPRETIVE_ONLY` authority boundary;
- a strict schema whose only provider-controlled values are opaque citation
  selections.

The code validates the returned JSON again locally. Unknown citations, missing
required focus citations, duplicates, unexpected fields, malformed values, or
an authority-boundary change reject the guide before any artifact exists. It
then generates the headline, summary, observations, and human questions
locally. Verification recomputes that controlled rendering; a re-sealed
artifact with altered prose fails verification.

The guide is not a priority order. Its citations are normalized to the
deterministic packet order, and the complete deterministic Verification Graph
remains visible beside it.

## Generate a briefing

Generate and verify a normal local export first:

```bash
python3 -m lifeline plan scenarios/flood_v1.json \
  --out out \
  --reference-time 2026-07-17T11:00:00Z

export OPENAI_API_KEY="..."
python3 -m lifeline narrate --out out --model gpt-5
python3 -m lifeline verify --out out
```

`OPENAI_API_KEY` is read only from the local process environment. It is not
written to `out/`, returned by the CLI, placed in a browser, or committed to
the repository.

## Local development adapter: NVIDIA

OpenAI Responses remains the default and the documented integration for this
OpenAI hackathon. For local testing only, a coordinator without an OpenAI key
may use NVIDIA's documented OpenAI-compatible Chat Completions endpoint:

```bash
export NVIDIA_API_KEY="..."
python3 -m lifeline narrate --out out \
  --provider nvidia
python3 -m lifeline verify --out out
```

This adapter changes only the external citation selector. It sends the same
minimal sealed packet, has no write or operational tool, and its plain JSON
response is rejected unless it exactly matches the closed reading-guide
contract. The resulting artifact declares `nvidia_chat_completions`; it must
never be represented as an OpenAI-generated artifact. No key is written to
the export, browser, logs, or repository.

For the local Operations console, configure the server process rather than the
browser request:

```bash
export NVIDIA_API_KEY="..."
export LIFELINE_AGENT_PROVIDER=nvidia
python3 -m lifeline serve --out out --port 8094
```

Without these development variables, `LIFELINE_AGENT_PROVIDER` defaults to
`openai` and `LIFELINE_AGENT_MODEL` defaults to `gpt-5`. When the provider is
explicitly `nvidia` and no model override is set, it defaults to NVIDIA's
instruction-tuned `meta/llama-3.1-8b-instruct` rather than a reasoning model.

The command writes:

```text
out/
├── agent_briefing.json
└── agent_briefing.seal.json
```

The artifact is separately sealed and binds its own packet digest to the exact
plan and Verification Graph digests. `lifeline verify --out out` checks that
binding, the opaque guide's citation contract, and the exact controlled
rendering.

Open the local room afterwards:

```bash
python3 -m lifeline serve --out out --port 8094
```

Then visit `http://127.0.0.1:8094/web/room.html?mode=live`. The purple Agent
Briefing panel shows the controlled, cited output only if its browser-verifiable
seal and input bindings match. The local operations console performs the same
digest, version, and input-binding checks before it displays its short-lived
response. Without an artifact, the deterministic room works normally and
labels the feature as optional.

## Generate from Local Operations

The local operations console also exposes **Generate cited agent briefing**
after a coordinator has computed a sealed plan for a selected incident. It
calls:

```text
POST /api/incidents/{incident_id}/agent-briefing
```

This route requires a local `coordinator` token even though the returned guide
has no operational authority. The reason is data egress: the route sends the
same minimal sealed packet to the optional external provider. It does not
write a report, revision, plan, approval, alert, or dispatch record. The
response contains a separately sealed short-lived artifact for the current
incident plan; recomputing a plan requires a new briefing request. By default
the endpoint includes the latest event only (`after_revision = current - 1`).
The operations UI supplies that value explicitly, so the locally rendered guide
can expose what changed between the immediately preceding revision and the
current plan.

The server chooses its provider and model through
`LIFELINE_AGENT_PROVIDER` (default `openai`) and `LIFELINE_AGENT_MODEL`
(default `gpt-5`, or `meta/llama-3.1-8b-instruct` for NVIDIA), never from
browser input. This keeps provider and model
selection out of untrusted client requests. If the matching local API key is
missing or the provider rejects the request, the endpoint returns an explicit
unavailable error and the incident remains unchanged.

## What verification does and does not prove

The seal proves that the recorded controlled briefing and its declared input
bindings were not altered after sealing. The contract proves that its citation
guide came from the supplied sealed packet, that its declared role stayed
interpretive-only, and that every displayed sentence equals LIFELINE's local
template rendering.

Neither mechanism proves that the provider selected the most useful or complete
citations. This is why the guide is visibly non-authoritative, is not a priority
order, and is never read as input by another LIFELINE component.

## Demo line

> The deterministic kernel decides what evidence is admissible. The optional
> OpenAI guide can point a person to sealed evidence, while LIFELINE renders
> the words locally. Neither can change the plan or make the decision.
