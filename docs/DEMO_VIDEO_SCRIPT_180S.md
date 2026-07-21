# LIFELINE — 3–4 Minute Judge Demo

**Format:** edited YouTube video

**Audience:** hackathon judges and technical reviewers

**Data:** synthetic flood incident only
**Author:** ChatGPT 5.6 Terra

## Core rule

Every shot must answer one question: **what did the system prove, refuse, or
leave for a human?** Do not spend video time showing filenames or explaining
the repository tree. Show the consequence on screen, then cut.

The public room demonstrates the sealed read model. The local operations room
demonstrates ingestion, revisions, alerts, authentication, and approvals. The
terminal demonstrates trace, export, and offline verification. These are three
surfaces of the same synthetic incident, not three unrelated demos.

## Before recording

Prepare two browser windows:

1. Static synthetic room: `web/room.html?mode=demo`
2. Local operations room: `http://127.0.0.1:8788/web/ops.html`

Prepare one local export with trace enabled:

```bash
python3 -m lifeline plan scenarios/flood_v1.json \
  --out /tmp/lifeline-video-out \
  --reference-time 2026-07-17T11:00:00Z
python3 -m lifeline simulate scenarios/flood_v1.json \
  scenarios/flood_v1_whatifs.json \
  --out /tmp/lifeline-video-out \
  --reference-time 2026-07-17T11:00:00Z
python3 -m lifeline verify --out /tmp/lifeline-video-out
```

Bootstrap a local admin before recording the operations segment. Keep the
token outside the recording until the approval shot.

For the optional OpenAI segment, set `OPENAI_API_KEY` only in the terminal
running the local server. Never paste it into a browser, the repository, or the
recording. If the key is unavailable, omit only the Agent Briefing shot; the
deterministic incident path remains complete.

## Timeline and spoken script

### 0:00–0:12 — Hook: the map is already full

**Screen:** synthetic incident room, map and markers visible.

**Voiceover:**

> During a disaster, the hardest problem is not moving faster. It is knowing
> which facts are safe to act on when the reports disagree.

Show the red, green, blue, and amber markers. Do not introduce the product
with a logo animation; start with the incident.

### 0:12–0:28 — Briefing: compress the situation, preserve uncertainty

**Screen:** run of show and sealed briefing counters.

Point quickly at:

- requests, resources, shelters, and route reports;
- proposals awaiting decision;
- items needing human review;
- validation warnings.

**Voiceover:**

> LIFELINE begins with a deterministic briefing. It summarizes the incident,
> but it does not turn urgency into a priority score or a dispatch command.

This is the visible consequence of the briefing and export layers.

### 0:28–0:48 — Evidence and validators

**Screen:** map popups and validation findings.

Click or zoom into:

- a verified operator report;
- an unverified public report;
- a stale report;
- a route with conflicting observations.

**Voiceover:**

> Every report keeps its source, timestamp, verification state, and freshness.
> Validators can downgrade evidence, but they cannot manufacture confidence.

Show `STALE_REPORT` and the contradiction banner. Let the audience see that
the conflicting route remains visible instead of disappearing from the map.

### 0:48–1:08 — Verification Graph

**Screen:** Verification Graph panel.

Scroll through one clear node and one blocked node. Hold briefly on:

- `supports`;
- `refutes`;
- `required artifacts`;
- `unresolved`;
- `action_required`.

**Voiceover:**

> A blocked result is not a dead end. The graph shows what supports a claim,
> what refutes it, what artifact is missing, and what a human must verify next.

### 1:08–1:30 — Deterministic plan

**Screen:** proposed and review-required proposal cards.

Show the two proposed paths, then the two human-review gates.

**Voiceover:**

> The planner proposes only combinations that satisfy the hard constraints:
> evidence, resource availability, route usability, medical compatibility,
> and destination capacity. Everything else becomes explicit review work.

Do not explain the algorithm. Show the reasons on the cards.

### 1:30–1:50 — Simulation: change one fact

**Screen:** simulated alternatives.

Focus on “North bridge confirmed closed.”

**Voiceover:**

> Now change one declared assumption: the north bridge is confirmed closed.
> The pipeline is re-run. The boat proposal disappears into human review.
> No alternative is silently selected and no winner is invented.

Briefly flash the South access and Shelter A variants to show that this is a
family of explicit what-if analyses, not a single hard-coded animation.

### 1:50–2:10 — Operations: the world changes

**Screen:** local `ops.html`, selected incident and attention feed.

Perform or cut between:

1. create the synthetic incident;
2. append a typed report;
3. show the new revision and alert;
4. supersede a route report with a correction.

**Voiceover:**

> The world is not edited in place. A new report creates a new revision. A
> correction preserves the previous report in the event ledger and changes the
> current snapshot.

Hold on `REPORT_SUPERSEDED`, the revision number, and `authority: none` in the
attention feed.

### 2:10–2:28 — Authentication and approvals

**Screen:** local plan card in `ops.html`.

Show the coordinator token only for this segment.

Perform three rapid actions:

1. approve one current `PROPOSED` item;
2. attempt to approve it again;
3. attempt to approve a blocked or stale item.

**Voiceover:**

> Approval requires an authenticated coordinator and the exact current plan.
> Duplicate decisions, stale hashes, and blocked proposals are refused.
> Approval records accountability; it never dispatches anything.

Show the recorded entry index and the rejection messages.

### 2:28–2:43 — Optional OpenAI Agent Briefing

**Screen:** the local `ops.html` plan card.

Click **Generate cited agent briefing**. Keep the coordinator token out of
frame. Show the returned headline, one observation, one question for a human,
and its citation IDs.

**Voiceover:**

> The deterministic kernel decides what evidence is admissible. The optional
> OpenAI agent receives only that sealed evidence packet. It explains what is
> happening with citations, but it has no tools to alter a report, plan,
> approval, alert, or dispatch.

This is the OpenAI moment. Do not present the agent as an emergency authority
or show it giving a recommendation.

### 2:43–2:58 — Trace and export

**Screen:** terminal, then output directory.

Show a short trace inspection: scenario evidence, planner call, decision, seal.
Then show:

```text
plan.json
plan.seal.json
verification.json
verification.seal.json
room.geojson
simulation.json
simulation.seal.json
trace.sqlite
```

**Voiceover:**

> The run also produces a trace of what the kernel did and a portable bundle:
> plan, evidence graph, map layer, simulations, and independent seals.

### 2:58–3:18 — Verify, tamper, close

**Screen:** terminal.

First show:

```text
plan seal: PASS
verification seal: PASS
verification semantics: PASS
approvals chain: PASS
incident ledger: PASS
```

Then cut to a controlled local edit of a verification action and run verify
again:

```text
verification seal: PASS
verification semantics: FAIL
```

**Voiceover:**

> A hash proves that bytes stayed the same. The semantic verifier proves that
> the artifact still respects the human-authority contract.

Close on the room and say:

> LIFELINE does not claim complete truth. It separates evidence, uncertainty,
> simulation, and human decisions — and leaves a verifiable record of the path
> between them.

## Editing notes

- Use hard cuts between the three surfaces; do not waste time on navigation.
- Keep the synthetic-data ribbon visible at least once.
- Never show a real token, real location, or real emergency data.
- Put the current stage in a small corner caption: `INGEST`, `CORROBORATE`,
  `PLAN`, `SIMULATE`, `REVISE`, `APPROVE`, `NARRATE`, `VERIFY`.
- If the full 180 seconds feels dense, remove the second simulation variant,
  not the revision or verification shots. Those two prove the system is more
  than a static planner.
