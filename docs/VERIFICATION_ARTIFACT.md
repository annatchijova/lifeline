# Verification artifact contract

## Purpose

`verification.json` is LIFELINE's deterministic evidence-gap read model. It
turns a completed planning run into inspectable verification work without
changing the planner, ranking people, or authorizing a dispatch.

It follows the domain-neutral discipline of VIGÍA's reasoning trace:

- an examined report is recorded as `ANALYZED`;
- an absence of examination must never be represented as supporting evidence;
- a contradiction remains explicit instead of being averaged into a claim of
  certainty; and
- a blocked result identifies the evidence a human would need before a plan is
  recomputed.

The implementation is native to LIFELINE. It does not import VIGÍA's forensic
scoring, CAIE artifact types, float-based scores, or forensic response actions.

## Authority boundary

The artifact is explanatory only.

- It does not select a resource, route, shelter, or recipient.
- It does not rank people, assign a priority score, or recommend a dispatch.
- `CLEAR` means the deterministic evidence gates used by an already-produced
  proposal were satisfied. It does **not** mean that the proposal is approved.
- `BLOCKED` means the kernel could not establish a proposal from the available
  evidence or constraints. A required artifact permits a human to update and
  recompute the scenario; it does not guarantee feasibility.

Human approval remains a separate, authenticated, hash-chained event.

## Artifact shape

The top-level payload is versioned and contains the exact SHA-256 digest of the
plan it explains:

```json
{
  "verification_version": 1,
  "scenario_id": "...",
  "plan_sha256": "...",
  "nodes": [],
  "validation_findings": [],
  "limitations": []
}
```

Each node has a request identifier, the planner outcome, a `CLEAR` or
`BLOCKED` disposition, a stable `reason_code`, an `action_required` label,
the `required_artifacts` needed to revisit the block, and explicit
`supports`, `refutes`, and `unresolved` fields.

Evidence references include entity type and identifier, source metadata,
freshness, verification state, and observation state. A `CLEAR` node includes
the request, resource, shelter, and route reports used by the proposal. A
blocked request can name, for example:

- `REQUEST_UNVERIFIED` → `authorized_request_confirmation`;
- `REQUEST_CONTRADICTION` →
  `independent_authorized_request_confirmation`;
- `REQUEST_STALE` → `fresh_authorized_request_report`; or
- `FEASIBILITY_NOT_ESTABLISHED` → a human-verified feasible resource, route,
  and destination capacity.

When reports for a destination route disagree, `ROUTE_CONTRADICTION` preserves
the open and closed assertions in separate `supports` and `refutes` lists. It
asks for `independent_current_route_status`; it does not select an alternative
route or infer that either report is correct.

`RESOURCE_EVIDENCE_UNUSABLE` and `SHELTER_EVIDENCE_UNUSABLE` are emitted only
when the reported resource or shelter meets the declared factual constraints
but is excluded by verification state or freshness. A purely physical shortfall
(for example, no vehicle with sufficient capacity) remains an explicit
`FEASIBILITY_NOT_ESTABLISHED` limit; the artifact does not imply that an
unverified report would make it feasible.

Access to the pickup zone is modeled separately from the route to the
destination. `ACCESS_ROUTE_CONTRADICTION` and
`ACCESS_ROUTE_EVIDENCE_UNUSABLE` show why a factually suitable resource cannot
reach a request. They request current access-route evidence and never imply
that another resource should be sent.

The contract deliberately retains unresolved evidence rather than deriving an
unjustified recommendation from it.

## Sealing and verification

The standalone export writes these sibling artifacts:

```text
plan.json ────────────────► plan.seal.json
     │                           SHA-256(plan.json)
     │
     └── plan_sha256 ─► verification.json ─► verification.seal.json
                                      SHA-256(verification.json)
```

`lifeline verify --out out` recomputes both hashes, confirms that the
verification payload and its seal refer to the exact sealed plan, and validates
the contract itself. The semantic check requires every plan proposal to be
covered, rejects proposal-status disagreement and duplicate nodes, and rejects
any action outside a closed vocabulary of verification work even if a modified
artifact has been sealed again. This is an allowlist rather than a blocklist:
`DEPLOY_*`, `DISPATCH_*`, or any future authority-shaped label is not a valid
blocked-node action. `CLEAR` has its own single action,
`HUMAN_APPROVAL_REQUIRED`. The generator and semantic verifier share this
single action vocabulary, so an implementation cannot add a generated action
without also making an explicit contract change.
It does not certify the truth of a field report: that remains a new scenario
and recomputation. The verification artifact intentionally remains a sibling
rather than being folded into `plan.json`: it explains the decision path but
never becomes planning authority.

Plans returned from `POST /api/incidents/{id}/plan` carry the same pair in
memory. Their verification payload also records `incident_revision` and
`incident_scenario_sha256`, while its seal binds to the exact plan hash. A
changed report, correction, or reference time produces a different plan hash,
so it cannot be silently reused for an approval.

## Freshness gate

Requests now require both `verification_state == "verified"` and a freshness
level other than `low` before reaching the planner. A stale request becomes
`NEEDS_HUMAN_REVIEW` with the reason `stale report`, and the verification
artifact names the fresh report required to recompute it.

## Limits

- The artifact can only describe reports represented in the scenario; it does
  not infer unreported field conditions.
- It does not prove that an updated report is true. Human verification and the
  normal schema/validator boundary remain required.
- SHA-256 seals detect alteration of the artifacts present. As with the
  approval and incident ledgers, detecting removal of a final artifact requires
  an external anchor.
