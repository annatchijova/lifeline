# Export Recovery Boundary

**Author:** ChatGPT 5.6 Terra
**Status:** Implemented and regression-tested

LIFELINE exports a small set of sibling artifacts into the caller-selected
output directory.  The directory also contains long-lived local state such as
operator and incident databases, so replacing the whole directory is neither
safe nor appropriate.

## Per-artifact publication

Each exported JSON artifact is rendered into a temporary file in the same
output directory, flushed and `fsync`'d, then published with `Path.replace()`.
Within that directory and filesystem, a reader sees either the previous whole
artifact or the new whole artifact; it never sees a prefix written directly
into the public filename.

This applies to:

- `plan.json` and `plan.seal.json`
- `verification.json` and `verification.seal.json`
- `room.geojson`
- `simulation.json` and `simulation.seal.json`

If publication fails before replacement, the previous artifact remains in
place. The temporary file is removed by the publishing process when it can
handle the failure.

## Deliberate non-guarantee: a multi-file snapshot

The sibling files are not a filesystem transaction. A process can stop after
publishing a new `plan.json` and before publishing the matching
`plan.seal.json`. That leaves two complete files from different generations.
LIFELINE treats this as an invalid state, not as a usable plan:

```text
new plan.json + old plan.seal.json
              │
              ├─ lifeline verify  -> FAIL
              ├─ browser UI       -> seal verification fails; approvals disabled
              └─ POST approval    -> 500 refusal; no ledger entry is appended
```

The same fail-closed rule applies to unreadable or truncated plan/seal files.
The API returns a controlled refusal rather than dropping the HTTP connection;
the offline verifier returns exit code `1` and prints `FAIL` rather than a
traceback.

## Evidence

The regression suite covers three discriminating recovery cases:

1. A synthetic failure before replacing `plan.json` leaves the old file byte
   for byte unchanged and removes the staging file.
2. A synthetic interruption after replacing `plan.json` but before its seal
   makes approval return a refusal and leaves `approvals.jsonl` absent.
3. A truncated `plan.json` produces the same no-approval API result and is
   reported as `FAIL` by `lifeline verify` without a traceback.

This is an integrity and recovery boundary, not a guarantee of report truth or
an authority to dispatch. Approval remains a separate authenticated local
action.
