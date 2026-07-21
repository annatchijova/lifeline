# Building LIFELINE with Codex

LIFELINE is led by **Anna Tchijova**. Codex is used here as a coding and
review assistant: it helps turn product direction into small, inspectable
changes, but it is not an emergency authority, a source of operational facts,
or an owner of project decisions.

This note records the collaboration method because it affects the quality of
the software. The important claim is not that an assistant wrote code quickly;
it is that decisions, limits, and evidence remain reviewable after the session.

## Division of responsibility

| Area | Anna Tchijova | Codex |
|---|---|---|
| Product direction and scope | Defines the problem, priorities, user experience, and what is acceptable to ship. | Maps that direction to concrete work and flags trade-offs or missing decisions. |
| Architecture and safety boundaries | Owns the non-negotiable limits: no autonomous dispatch, evidence before narrative, and human approval. | Checks that changes preserve those boundaries and proposes tests for them. |
| Implementation | Reviews and accepts the resulting code and documentation. | Inspects the repository, implements scoped changes, and explains what changed. |
| Verification | Decides whether evidence is sufficient to merge, publish, or present. | Runs relevant tests, reads the output, performs targeted audits, and reports limits as well as successes. |
| Git and publication | Authorizes commits, pushes, releases, hosting, and any external communication. | Prepares focused commits when requested; does not push, publish, or contact external systems without that instruction. |

No model name is used as evidence that a LIFELINE plan is correct. A review by
Codex is useful engineering input, not an attestation, emergency authorization,
or substitute for local responders and coordinators.

## The working loop

1. **Start with the live tree.** Codex reads the relevant code, tests, and
   existing documentation before proposing a change. It does not assume that a
   design document describes the current implementation.
2. **State the boundary.** Each task is checked against LIFELINE's core
   limits: deterministic planning, explicit provenance and freshness,
   uncertainty that can block a proposal, and no autonomous dispatch.
3. **Make a narrow change.** New behavior is kept local and typed where
   possible. For example, reports enter through schema validation, changes
   create append-only ledger events, and alerts express attention rather than
   orders.
4. **Verify the behavior.** Tests are added or updated for the normal path and
   for a failure or misuse path. Test results, static checks, and any manual
   browser observation are treated as distinct evidence with their own scope.
5. **Audit the result.** Codex checks diffs, looks for mismatches between the
   claim and the code, and calls out false-positive/false-negative risk rather
   than turning incomplete coverage into a clean bill of health.
6. **Commit intentionally.** Changes are grouped by their purpose and use an
   English, why-focused commit message. Commits are made only after Anna asks
   for them. This repository does not add automatic AI co-author trailers.

The loop is iterative. A finding can change the design; a design can reveal a
missing test; and a test can show that the original product assumption was too
strong. Preserving that correction path matters more than appearing finished.

## How Codex is helping LIFELINE move forward

The current collaboration has accelerated several otherwise separate pieces of
work while keeping them connected to the same safety model:

- converting the synthetic flood scenario into a sealed, inspectable plan and
  a static judge demo that also works when opened directly from a file;
- separating the public demo from the loopback-only operational backend so a
  hosted page cannot accidentally become a dispatch surface;
- adding a validated local incident store, append-only hash-linked event
  history, explicit corrections, deterministic planning from a stored revision,
  and a polling-oriented attention feed;
- improving map contrast and interaction so evidence, review state, and
  priority remain legible under real presentation conditions;
- documenting the remaining gaps instead of masking them: identity,
  authorization, recipient consent, external alert delivery, offline sync, and
  real incident integration are not claimed as complete.

This is leverage, not delegated accountability. Codex makes it faster to
inspect alternatives, implement a chosen direction, and challenge edge cases.
Anna remains responsible for the direction, the evidence threshold, and every
decision to expose software beyond the local development environment.

## Runtime boundary

LIFELINE's planning path is deterministic local code. It validates structured
scenario data, applies declared constraints, exports a sealed plan, and records
human approvals separately. Codex does not run inside that path and does not
choose resources, priorities, routes, or actions.

An optional language model may narrate only a completed, locally verified plan
and Verification Graph under an explicit policy. It must never be allowed to
invent facts, upgrade evidence, alter a plan, or issue instructions as an
operational authority. Agent Briefing Mode receives no mutation or approval
tools; it produces a separately sealed, cited interpretation bound to its
inputs. If it is unavailable, the deterministic plan and its audit trail still
exist. See [`AGENT_BRIEFING_MODE.md`](AGENT_BRIEFING_MODE.md).

## Evidence and limits of this note

This document describes the development workflow, not an independent security
certification or operational validation. Passing tests demonstrate only the
cases they execute. Local browser checks do not prove a public deployment.
Hash chains demonstrate detectable alteration within their stated threat model;
they do not establish identity or recipient authorization.

Before LIFELINE is used with real people or operational data, the project still
needs a signed role and authorization design, a data protection review,
consent and retention rules, a delivery-failure policy for external alerts, and
validation with the responsible local emergency organizations.
