# Red-Team Audit — LIFELINE

**Date:** 2026-07-19

**Author:** ChatGPT 5.6 Terra
**Method:** Abductive Engineering (abduction → deduction → induction) and adversarial review

## Scope and evidence

This was a read-only audit of the working tree based on commit
`9822ed11907d4fdbdea809ae4e1524607828719a`, including the then-uncommitted
verification-contract work. No source files were changed during the audit.

- Runtime: Python 3.12.3
- Synthetic fixture: `scenarios/flood_v1.json`
- Fixture SHA-256: `347c31df8e241979eb1363f9b3a1db30ce12c9ea59151aadd56fc434f63207a1`
- Regression suite: `70 passed`

## Threat model

The confirmed findings use explicit, local capabilities. The attacker may:

- issue two concurrent, otherwise valid approval attempts;
- write to an `out/` directory while being unable to read every file readable
  by the loopback server process;
- race two initial bootstrap attempts against an empty operator registry; or
- control a report timestamp that is otherwise accepted as verified.

The attacker does not modify source code, compromise the host kernel, hold an
existing coordinator token unless the finding says so, or use an external
network. LIFELINE remains a loopback-only alpha prototype and is not an
emergency service.

## Epistemic legend

- **CODE FACT** — directly observed in source.
- **PLAUSIBLE HYPOTHESIS** — supported by architecture but not executed.
- **CONFIRMED BY INDUCTION** — a predicted outcome was reproduced.
- **FALSIFIED** — the predicted outcome did not occur.

## Executive summary

| ID | Severity | Level | Bucket | Finding |
| --- | --- | --- | --- | --- |
| RT-01 | Medium | CONFIRMED BY INDUCTION | Software vulnerability | Concurrent incident approvals can corrupt an approval chain. |
| RT-02 | Medium, conditional | CONFIRMED BY INDUCTION | Software vulnerability | A public artifact filename can serve a symlink target outside `out/`. |
| RT-03 | Medium, conditional | CONFIRMED BY INDUCTION | Software vulnerability | Concurrent initial bootstraps can create two administrators. |
| RT-04 | Low | CONFIRMED BY INDUCTION | Software vulnerability | A future timestamp less than one second ahead can pass the temporal gate. |

## Findings

### RT-01 — Concurrent incident approvals corrupt the ledger

**Severity:** Medium

**Epistemic level:** CONFIRMED BY INDUCTION
**Bucket:** Software vulnerability

**Surprise.** An approval is supposed to be unique for a `(request_id,
plan_sha256)` pair and the resulting approval history is supposed to remain
hash-chain-verifiable.

**Code fact.** `IncidentStore.record_approval()` reads and checks the current
approval log before calling `append_entry()`. Neither operation is protected by
a per-incident lock or a single database transaction. `append_entry()` then
reads the file again and derives its own index and previous hash.

**Deduction.** If two valid approval requests cross the duplicate check before
either append, both can derive the same entry index and previous hash. The
expected outcome is two successful calls followed by a chain verification
failure.

**Induction.** A synthetic incident was created in a temporary directory. Two
threads called `record_approval()` with the same valid proposed item while a
`Barrier(2)` was placed immediately before the original `append_entry()`.
Observed result:

```text
responses=2
entries=2
same request_id and plan_sha256 in both entries
indices=[0, 0]
verify_chain -> FAIL: entry #1: index 0 breaks the sequence
```

**Causal chain.**

```text
two valid concurrent calls
    → both observe no prior decision
    → both derive genesis/index 0 in separate append operations
    → both append
    → the chain contains two index-0 entries and becomes unverifiable
```

**Threat-model precondition.** Two concurrent valid incident-approval calls
reach the threaded local server or `IncidentStore` directly. No forged token,
source modification, or network exposure is required.

### RT-02 — Public artifact serving follows symlinks

**Severity:** Medium, conditional

**Epistemic level:** CONFIRMED BY INDUCTION
**Bucket:** Software vulnerability

**Surprise.** `PUBLIC_ARTIFACTS` is intended to limit `/out/` to a small list
of displayable files.

**Code fact.** The server checks a requested basename against the allowlist,
then delegates file serving to `SimpleHTTPRequestHandler`. That handler follows
symlinks.

**Deduction.** If an actor can replace `out/plan.json` with a symlink to a file
readable by the server process, an unauthenticated loopback request to the
allowed filename will receive the target bytes.

**Induction.** In a temporary directory, `out/plan.json` was a symlink to a
synthetic file outside `out/` containing `LIFELINE_AUDIT_SYNTHETIC_SECRET`.
`GET /out/plan.json` returned exactly that string.

**Threat-model precondition.** The attacker can write the selected `out/`
artifact path but cannot directly read a target file readable by the server
process. On a single-user default setup this condition may not arise; it is a
real trust-boundary issue for shared or differently privileged local setups.

### RT-03 — Initial administrator bootstrap is not atomic

**Severity:** Medium, conditional

**Epistemic level:** CONFIRMED BY INDUCTION
**Bucket:** Software vulnerability

**Surprise.** Bootstrap is documented as creating the first local admin exactly
once.

**Code fact.** `OperatorStore.bootstrap()` checks for any existing row and then
inserts an admin. The check and insert are not protected by `BEGIN IMMEDIATE`
or a singleton registry constraint.

**Deduction.** If two callers both read an empty registry before either insert,
both inserts can commit because their distinct operator IDs satisfy the primary
key constraint.

**Induction.** Two `OperatorStore` instances targeting the same temporary
database were held at a barrier immediately after their empty-registry read.
Both bootstrap calls returned success; the database contained `admin-one` and
`admin-two`, each with role `admin`.

**Threat-model precondition.** Two local processes can race the first setup of
the same empty registry. This is not a remote bootstrap path.

### RT-04 — Sub-second future reports evade the future-time gate

**Severity:** Low

**Epistemic level:** CONFIRMED BY INDUCTION
**Bucket:** Software vulnerability

**Surprise.** The documented temporal boundary says future-dated reports are
downgraded before they can support a proposal when a reference time is given.

**Code fact.** `_age_minutes()` applies `int()` to seconds before integer
minute division. For a negative delta between zero and one second, truncation
produces zero rather than a negative value.

**Deduction.** A report timestamp exactly 0.5 seconds after the supplied
reference time should be treated as present rather than future, retaining a
declared `high` freshness.

**Induction.** A verified synthetic request was changed to
`2026-07-17T11:00:00.500000+00:00` and planned against
`2026-07-17T11:00:00+00:00`. Observed result: no `FUTURE_TIMESTAMP` finding,
freshness remained `high`, and the request was `PROPOSED`.

**Threat-model precondition.** A report can supply an otherwise accepted,
verified timestamp. The bypass window is less than one second, hence the low
severity, but it violates a fail-closed invariant.

## Discarded vectors

| Vector | Prediction | Result |
| --- | --- | --- |
| Textual traversal `/out/../private.txt` | A file outside `out/` is served. | **FALSIFIED** — 404. |
| Percent-encoded traversal `/out/%2e%2e/private.txt` | A file outside `out/` is served. | **FALSIFIED** — 404. |
| `/.git/config` | Repository metadata is served. | **FALSIFIED** — 404. |

These falsifications do not weaken RT-02: path normalization blocks ordinary
traversal while symlink following remains a distinct filesystem-boundary
failure.

## Boundary observations, not findings

- A holder of a `reporter` token can submit a report marked `verified`; the
  planner trusts that provenance state. This is a **threat-model assumption**:
  reporters must be authorized to make that attestation. It is not a bypass if
  that role is trusted as the attesting authority.
- Recomputable SHA-256 seals are not classified as an exploit. A hash proves
  integrity of presented bytes, not the truth of an attacker-controlled input;
  that is a stated limitation, not a LIFELINE-specific cryptographic break.
- The server startup message says there is no authentication even though the
  API authenticates bearer tokens. This is a **CODE FACT** and an operational
  documentation/sign mismatch, not an authentication bypass.
- `OperatorStore` stores a `revoked_at` field, but the current CLI/API exposes
  no token revocation workflow. This is hardening and product-boundary work,
  not a demonstrated exploit.

## Recommendations

1. Make incident approvals atomic across the duplicate check and append. A
   SQLite-backed uniqueness constraint is stronger than an in-process lock and
   remains safe if more than one process targets the same local state.
2. Serve public artifacts only after resolving their path and proving that the
   resolved target remains inside `out/`; reject symlinks and non-regular files.
3. Make bootstrap singleton creation transactional, or use a dedicated
   singleton registry row with a database constraint.
4. Test futureness from the raw `timedelta` before any minute rounding.
5. Correct the startup message and decide whether revocation belongs in the
   prototype's explicit scope.

This report does not certify operational suitability. It records only the
executed evidence above and the stated local threat model.
