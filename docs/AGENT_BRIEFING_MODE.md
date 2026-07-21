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
cited agent_briefing.json (separate seal)
              ↓
          human coordinator
```

The deterministic kernel remains authoritative for feasibility. The
Verification Graph remains authoritative for evidence gaps. The agent may only
explain those artifacts in natural language with supplied citation IDs.

It cannot:

- create or alter incidents, reports, revisions, findings, plans, or
  simulations;
- change verification or freshness states;
- choose a resource, rank people, recommend a dispatch, or issue instructions;
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

Only then does LIFELINE build a minimal packet containing the sealed briefing,
proposal read model, verification nodes, validation findings, and a closed list
of citation IDs. The packet deliberately excludes raw mutable incident data,
operator credentials, approval records, and all write endpoints.

For a persisted incident, the packet may also include a deterministic change
read model from the verified event ledger. Each change names its revision,
event type, entity, timestamp, and immutable event hash. Report payloads are
reduced through an allowlist of operational fields before they reach the model;
free-text source fields and other raw event content are not forwarded. This
lets the agent explain *what changed since a revision* without treating an
untrusted report string as instructions.

## OpenAI request policy

The implementation uses the OpenAI Responses API with:

- `store: false` (the request disables response storage; consult OpenAI's
  current data-controls documentation for the service-level retention policy);
- strict JSON Schema output;
- no OpenAI built-in tools;
- no custom function tools;
- an explicit `INTERPRETIVE_ONLY` authority boundary;
- a requirement that the headline, summary, every observation, and every
  question cite packet evidence.

The code validates the returned JSON again locally. Unknown citations, missing
citations, unexpected fields, malformed values, or an authority-boundary change
reject the narration before it is written.

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

The command writes:

```text
out/
├── agent_briefing.json
└── agent_briefing.seal.json
```

The artifact is separately sealed and binds its own packet digest to the exact
plan and Verification Graph digests. `lifeline verify --out out` checks that
binding as well as the narration's citation and authority contract.

Open the local room afterwards:

```bash
python3 -m lifeline serve --out out --port 8094
```

Then visit `http://127.0.0.1:8094/web/room.html?mode=live`. The purple Agent
Briefing panel shows the cited output only if its browser-verifiable seal and
input bindings match. Without an artifact, the deterministic room works
normally and labels the feature as optional.

## Generate from Local Operations

The local operations console also exposes **Generate cited agent briefing**
after a coordinator has computed a sealed plan for a selected incident. It
calls:

```text
POST /api/incidents/{incident_id}/agent-briefing
```

This route requires a local `coordinator` token even though the returned text
has no operational authority. The reason is data egress: the route sends the
same minimal sealed packet to the optional external provider. It does not
write a report, revision, plan, approval, alert, or dispatch record. The
response contains a separately sealed short-lived artifact for the current
incident plan; recomputing a plan requires a new narration request. By default
the endpoint includes the latest event only (`after_revision = current - 1`).
The operations UI supplies that value explicitly, so the result can say what
changed between the immediately preceding revision and the current plan.

The server chooses the model through `LIFELINE_AGENT_MODEL` (default `gpt-5`),
not from browser input. This keeps model selection out of untrusted client
requests. If `OPENAI_API_KEY` is missing or the provider rejects the request,
the endpoint returns an explicit unavailable error and the incident remains
unchanged.

## What verification does and does not prove

The seal proves that the recorded narration and its declared input bindings
were not altered after sealing. The contract proves that its citations came
from the supplied sealed packet and that its declared role stayed
interpretive-only.

Neither mechanism proves that model prose is true, complete, or appropriate
for an operational context. The model may still misunderstand a fact inside its
allowed packet. This is why the output is visibly non-authoritative and why no
other LIFELINE component reads it as input.

## Demo line

> The deterministic kernel decides what evidence is admissible. The optional
> OpenAI agent helps a person understand that evidence, with citations, but it
> cannot change the plan or make the decision.
