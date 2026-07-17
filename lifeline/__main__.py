"""Command-line entry point: python3 -m lifeline plan <scenario> [--out DIR]."""

from __future__ import annotations

import argparse
import sys

from lifeline.export import export_plan
from lifeline.scenario import ScenarioError, load_scenario, plan_scenario
from lifeline.trace import record_trace


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lifeline")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan", help="export a sealed plan and incident-room layers")
    plan_parser.add_argument("scenario", help="path to a schema-v1 scenario JSON file")
    plan_parser.add_argument("--out", default="out", help="output directory (default: out)")
    plan_parser.add_argument("--no-trace", action="store_true", help="skip the optional CRONOS planning trace")
    args = parser.parse_args(argv)

    try:
        seal = export_plan(args.scenario, args.out)
    except ScenarioError as error:
        print(f"scenario rejected: {error}", file=sys.stderr)
        return 2
    print(f"plan sealed sha256={seal['sha256']}")
    print(f"wrote plan.json, plan.seal.json, room.geojson to {args.out}/")
    if not args.no_trace:
        scenario = load_scenario(args.scenario)
        if record_trace(args.out, scenario, plan_scenario(scenario), seal):
            print(f"planning trace recorded in {args.out}/trace.sqlite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
