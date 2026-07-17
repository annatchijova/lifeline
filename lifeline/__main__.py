"""Command-line entry point: plan, serve, and verify subcommands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lifeline.approvals import ApprovalChainError, read_entries, verify_chain
from lifeline.export import export_plan, seal_digest
from lifeline.scenario import ScenarioError
from lifeline.trace import record_trace


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lifeline")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan", help="export a sealed plan and incident-room layers")
    plan_parser.add_argument("scenario", help="path to a schema-v1 scenario JSON file")
    plan_parser.add_argument("--out", default="out", help="output directory (default: out)")
    plan_parser.add_argument("--no-trace", action="store_true", help="skip the optional CRONOS planning trace")
    plan_parser.add_argument(
        "--reference-time",
        help="ISO 8601 time (with timezone) used to corroborate declared freshness; "
             "without it staleness checks are skipped and reported as unchecked",
    )

    serve_parser = subparsers.add_parser("serve", help="serve the incident room and approvals API on loopback")
    serve_parser.add_argument("--out", default="out", help="directory holding the exported plan (default: out)")
    serve_parser.add_argument("--port", type=int, default=8788)

    verify_parser = subparsers.add_parser("verify", help="verify the plan seal and the approvals chain offline")
    verify_parser.add_argument("--out", default="out", help="directory holding the exported plan (default: out)")

    args = parser.parse_args(argv)

    if args.command == "serve":
        from lifeline.server import serve
        serve(Path.cwd(), args.out, port=args.port)
        return 0

    if args.command == "verify":
        return _verify(Path(args.out))

    try:
        result = export_plan(args.scenario, args.out, args.reference_time)
    except ScenarioError as error:
        print(f"scenario rejected: {error}", file=sys.stderr)
        return 2
    print(f"plan sealed sha256={result.seal['sha256']}")
    print(f"wrote plan.json, plan.seal.json, room.geojson to {args.out}/")
    warns = sum(1 for finding in result.findings if finding.severity == "warn")
    if result.findings:
        print(f"validation findings: {len(result.findings)} ({warns} warn)")
        for finding in result.findings:
            print(f"  [{finding.severity}] {finding.code} {finding.entity_type}:{finding.entity_id} — {finding.detail}")
    if not args.no_trace:
        if record_trace(args.out, result.scenario, result.proposals, result.seal):
            print(f"planning trace recorded in {args.out}/trace.sqlite")
    return 0


def _verify(out_dir: Path) -> int:
    failed = False

    plan_path = out_dir / "plan.json"
    seal_path = out_dir / "plan.seal.json"
    if not plan_path.exists() or not seal_path.exists():
        print("plan seal: FAIL (plan.json or plan.seal.json missing)")
        failed = True
    else:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
        if seal_digest(plan) == seal.get("sha256"):
            print(f"plan seal: PASS (sha256={seal['sha256']})")
        else:
            print("plan seal: FAIL (plan.json does not match plan.seal.json)")
            failed = True

    approvals_path = out_dir / "approvals.jsonl"
    if not approvals_path.exists():
        print("approvals chain: ABSENT (no approvals recorded)")
    else:
        try:
            entries = read_entries(approvals_path)
            verify_chain(entries)
            print(f"approvals chain: PASS ({len(entries)} entries; tail truncation not detectable without an external anchor)")
        except ApprovalChainError as error:
            print(f"approvals chain: FAIL ({error})")
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
