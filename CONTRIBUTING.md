# Contributing to LIFELINE

LIFELINE is open infrastructure for human-approved humanitarian coordination.
Contributions should preserve the project's safety boundary: the kernel may
produce a transparent proposal, but it must never dispatch responders or make
an unreviewable decision about a person's value.

Before opening a change:

1. Read `README.md` and `docs/LIFELINE_OS_EN.md`.
2. State the contract and trust boundary for the change.
3. Add a test that would fail if the implementation were wrong.
4. Run `python3 -m pytest -q` and report the exact result.
5. Keep sealed decision artifacts deterministic and free of display floats.

Changes to schemas or exported artifacts must include an explicit versioning
decision and compatibility notes. Changes to approvals, seals, or validation
must include tamper and replay tests. Do not add model calls to the planning
authority path; narration belongs outside the kernel and must remain optional.

This project is licensed under the Apache License 2.0. By contributing, you
agree that your contribution is provided under that license.
