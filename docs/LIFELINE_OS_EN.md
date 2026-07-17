# LIFELINE OS — humanitarian coordination architecture

> **Given what we know, how can we coordinate help better without hiding uncertainty?**

LIFELINE is not marketed as “AI for disasters,” a dashboard, or a chatbot. It
is open infrastructure for humanitarian coordination during a crisis.

It turns operational facts — reports, resources, routes, capacity, and
approvals — into explainable proposals that an authorized human can review,
approve, correct, or reject. It does not replace emergency authorities, local
protocols, responders, or human judgement.

## The governing principle

```text
Data
  ↓
Validation
  ↓
Deterministic planning
  ↓
Human approval
  ↓
Optional narration
```

ChatGPT may narrate an approved plan and answer questions over already selected
evidence. It may not select resources, alter priorities, invent locations,
assert unverified facts, issue orders, or provide operational advice as an
authority.

If the model is unavailable, the plan and its audit trail still exist.

## Evidence is not narrative

During a flood, incompatible claims may coexist:

- one person reports that a bridge collapsed;
- another reports one hundred people trapped;
- a recent drone observation shows the bridge standing;
- a satellite image is four hours old.

LIFELINE must not collapse this into a false claim of certainty. Its output
must preserve the conflict:

```text
Route status: CONFLICTING
Sources: 3 contradictory reports
Freshness: low / medium / high, per source
Effect: no proposal relying on this route is produced
Next action: aerial verification or confirmation by an authorized source
```

Uncertainty is operational information. It is recorded, shown, and may block a
proposal; it is never hidden merely to make the map look complete.

## LIFELINE as a crisis operating system

```text
LIFELINE OS
│
├── Emergency Kernel
│   ├── facts, constraints, and operational states
│   ├── reproducible planning
│   ├── human roles and approvals
│   └── verifiable audit trail
│
├── Maps
├── Resources
├── Hospitals
├── Shelters
├── Volunteers
├── Communications
├── Drones and sensors
├── Verification
├── Logistics
└── AI assistants
```

AI assistants are applications inside the system, not its authority center. The
Emergency Kernel must remain useful without them.

## Minimum data contract

Every entity capable of affecting a plan needs provenance and state, not just a
pretty coordinate on a map.

### Report

```text
report_id
source / source_type
created_at / observed_at / received_at
location and precision
claim type
verification_state
freshness
contradictions
custody_hash
```

### Resource, route, and destination

```text
resource_id / capability / availability / capacity / current zone
route_id / origin / destination / state / freshness / alternate routes
shelter or hospital id / relevant open capacity / accessibility / status
```

### Proposal

```text
proposal_id
facts considered
constraints satisfied
options discarded and why
uncertainties blocking options
approval_state / approver / timestamp
trace_hash
```

## The kernel does not optimize people

LIFELINE does not assign human value or optimize a hidden “lives maximized”
score. It works with explicit, reviewable operational constraints chosen by
emergency managers:

- never exceed shelter or hospital capacity;
- never use unavailable or incompatible resources;
- never rely on closed, stale, or conflicting routes;
- minimize travel time among feasible alternatives;
- preserve minimum coverage across zones;
- handle critical needs only under the applicable verification protocol;
- retain alternate routes and resources;
- abstain when required information is missing.

The result is a **feasible proposal**, never an autonomous dispatch.

## Simulation: show alternatives, do not choose for people

While a team coordinates, LIFELINE can evaluate explicit simulated scenarios:

```text
Plan A → shelter capacity remains available, route is open
Plan B → better coverage if ambulance arrival is delayed
Plan C → fails if the north bridge is confirmed closed
Plan D → requires additional hospital capacity
```

Simulation exposes dependencies and fragility. It must not produce an opaque
winner or replace local expertise. Every result must disclose its assumptions,
timestamps, active constraints, unmodelled resources, differences between
plans, and model limitations.

Initial simulations run only on synthetic data or operational data explicitly
authorized for simulation.

## Verification budget: Thompson Sampling outside authority

MUTANTE's Bayesian-bandit approach can inform a **Verification Budget
Allocator**: a component that proposes which verification action could reduce
operational uncertainty most effectively.

Candidate actions include calling a source, checking shelter capacity,
requesting a geolocated photo, querying route status, checking a sensor, or
asking a local response team for confirmation.

It may not select who receives aid, impose a rescue priority, or send an
order. Its domain is the **queue of verifiable questions**, not dispatch.

### Safe adoption path

1. **Offline laboratory:** campaigns over synthetic and historical scenarios,
   with no operational effect.
2. **Shadow mode:** generate verification proposals and compare them with
   human work, without presenting them as authority.
3. **Visible assistance:** a human chooses whether to use each proposal.
   Rejection is a valid outcome, not an error.

Because Thompson Sampling is probabilistic, each recommendation must record:

```text
policy version / random seed / posterior by arm
available evidence / proposed verification / observed outcome
human approval or rejection
```

Resource planning remains deterministic. A probabilistic component may never
silently enter its criteria.

## Patterns borrowed from the existing ecosystem

LIFELINE borrows ideas, not entire repositories or out-of-domain capabilities.

| Origin | Pattern | Responsible LIFELINE use |
|---|---|---|
| MNEME | Per-memory custody, quarantine, offline verifier | Per-report custody; an untrusted report cannot influence planning. |
| CRONOS | Decision traces captured during action | Facts, constraints, discarded options, and approval for every proposal. |
| Audit Chain | Independent verification and export | A verifiable incident timeline; future HMAC or external anchor. |
| STIGMERGY | Distributed consensus, cooldowns, Merkle ledger | Future local/NGO cells without a central coordinator; prevent resource oscillation. |
| VIGÍA | Abstention, named limits, evidence before narrative | Show conflict and missing information as uncertainty, not certainty. |
| CORVUS | Independent corroboration | Freshness, duplicate, location, and contradiction validators; never psychological analysis of victims. |
| raven-memory | Visible degradation and field memory | Post-incident knowledge base with declared semantic quality. |
| STYLOMETRY-CI | Source consistency | Optional institutional/sensor-source monitoring; never victim profiling. |
| MUTANTE | Adversarial campaigns and Thompson Sampling | Laboratory for conflicting reports, duplicates, injection, and verification budgets. |
| PHYLO | Reproducible competition between alternatives | Sandbox evaluation of policies; adopt only measured, reviewed improvements. |
| JANUS | Proportionality and process over blame | Support pressured operators without invasive monitoring or individual judgement. |

## Non-negotiable ethical boundaries

- No autonomous dispatches.
- No survival prediction or human-value scoring.
- No biometric collection or voice/identity cloning of victims.
- No psychological profiling of victims, volunteers, or staff.
- No simulated data presented as live facts.
- No hidden stale sources, conflicts, or coverage gaps.
- No sensitive content sent to a model without policy, notice, and explicit
  authorization.
- No generated narration treated as original evidence.

## First construction sequence

1. **Emergency Kernel:** data contracts, hard constraints, approval states,
   and abstention.
2. **Incident Room:** one synthetic flood map with resources, routes, shelters,
   and explainable proposals.
3. **Minimum custody:** report source/freshness/state plus planning traces.
4. **Alternative simulation:** comparable plans with visible assumptions.
5. **Adversarial laboratory:** duplicates, contradictory sources, impossible
   routes, and text injection.
6. **Optional narration:** only after the kernel and a human produce an
   approved plan.

## Product promise

LIFELINE does not promise complete knowledge of a crisis or human-level
judgement. It promises something more honest and useful:

> This is what we know. This is what we do not know. These are the feasible
> options. This is the evidence supporting them. And this is the person who
> approved the action.
