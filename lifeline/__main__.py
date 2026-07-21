"""Command-line entry point: plan, serve, and verify subcommands."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from lifeline.approvals import ApprovalChainError, read_entries, verify_chain
from lifeline.export import CanonicalizationError, export_plan, seal_digest
from lifeline.scenario import ScenarioError
from lifeline.trace import record_trace
from lifeline.verification import VerificationError, verify_payload


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

    simulate_parser = subparsers.add_parser(
        "simulate", help="run declared what-if variants and write a sealed comparison")
    simulate_parser.add_argument("scenario", help="path to a schema-v1 scenario JSON file")
    simulate_parser.add_argument("whatifs", help="path to a what-ifs JSON file with explicit variants")
    simulate_parser.add_argument("--out", default="out")
    simulate_parser.add_argument("--reference-time", help="ISO 8601 time (with timezone) for freshness corroboration")

    narrate_parser = subparsers.add_parser(
        "narrate", help="optionally create a provider-assisted briefing from verified sealed artifacts")
    narrate_parser.add_argument("--out", default="out", help="directory holding a completed local export")
    narrate_parser.add_argument(
        "--model", help="provider model (default: gpt-5 for OpenAI; meta/llama-3.1-8b-instruct for NVIDIA)")
    narrate_parser.add_argument(
        "--provider", choices=("openai", "nvidia"), default="openai",
        help="citation-selector provider (default: openai; NVIDIA is a local development adapter)",
    )

    serve_parser = subparsers.add_parser("serve", help="serve the incident room and approvals API on loopback")
    serve_parser.add_argument("--out", default="out", help="directory holding the exported plan (default: out)")
    serve_parser.add_argument("--port", type=int, default=8788)

    operator_parser = subparsers.add_parser("operator", help="bootstrap the local authenticated operator registry")
    operator_subparsers = operator_parser.add_subparsers(dest="operator_command", required=True)
    operator_init = operator_subparsers.add_parser("init", help="create the one-time local admin token")
    operator_init.add_argument("--out", default="out", help="directory holding the local operator registry")
    operator_init.add_argument("--id", required=True, help="lowercase local operator id, e.g. anna-coordinator")
    operator_add = operator_subparsers.add_parser("add", help="add a local role using an existing admin token")
    operator_add.add_argument("--out", default="out", help="directory holding the local operator registry")
    operator_add.add_argument("--id", required=True, help="lowercase local operator id")
    operator_add.add_argument("--role", required=True, choices=("reader", "reporter", "coordinator", "admin"))

    verify_parser = subparsers.add_parser("verify", help="verify the plan seal and the approvals chain offline")
    verify_parser.add_argument("--out", default="out", help="directory holding the exported plan (default: out)")

    args = parser.parse_args(argv)

    if args.command == "operator":
        from lifeline.auth import AuthError, OperatorStore
        try:
            operators = OperatorStore(Path(args.out) / "operators.sqlite3")
            if args.operator_command == "init":
                operator, token = operators.bootstrap(args.id)
            else:
                authorizer = operators.authenticate(getpass.getpass("Existing admin token: "))
                operator, token = operators.add(authorizer, args.id, args.role)
        except AuthError as error:
            print(f"operator operation refused: {error}", file=sys.stderr)
            return 2
        print(f"created local {operator.role}: {operator.operator_id}")
        print("store this token now; it is not retained in plaintext:")
        print(token)
        return 0

    if args.command == "serve":
        from lifeline.server import serve
        from lifeline.auth import OperatorStore
        if not OperatorStore(Path(args.out) / "operators.sqlite3").has_active_operator():
            print("server refused: bootstrap a local admin first with: lifeline operator init --out out --id <operator-id>", file=sys.stderr)
            return 2
        serve(Path.cwd(), args.out, port=args.port)
        return 0

    if args.command == "verify":
        return _verify(Path(args.out))

    if args.command == "simulate":
        from lifeline.export import export_simulation
        from lifeline.simulate import SimulationError
        try:
            seal = export_simulation(args.scenario, args.whatifs, args.out, args.reference_time)
        except (ScenarioError, SimulationError) as error:
            print(f"simulation rejected: {error}", file=sys.stderr)
            return 2
        print(f"simulation sealed sha256={seal['sha256']}")
        print(f"wrote simulation.json, simulation.seal.json to {args.out}/")
        print("simulated alternatives are not live facts; no winner is selected")
        return 0

    if args.command == "narrate":
        from lifeline.agent import AgentBriefingError, default_model, narrate_export
        try:
            artifact, seal = narrate_export(
                args.out, model=args.model or default_model(args.provider), provider=args.provider,
            )
        except AgentBriefingError as error:
            print(f"agent narration refused: {error}", file=sys.stderr)
            return 2
        print(f"agent briefing sealed sha256={seal['sha256']}")
        print(f"bound to plan={artifact['plan_sha256']} verification={artifact['verification_sha256']}")
        print("interpretive-only: no plan, approval, alert, or dispatch action was created")
        return 0

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
    plan: dict | None = None
    plan_digest: str | None = None
    verification: dict | None = None
    verification_digest: str | None = None

    plan_path = out_dir / "plan.json"
    seal_path = out_dir / "plan.seal.json"
    if not plan_path.exists() or not seal_path.exists():
        print("plan seal: FAIL (plan.json or plan.seal.json missing)")
        failed = True
    else:
        try:
            plan = _read_json_object(plan_path)
            seal = _read_json_object(seal_path)
            plan_digest = seal_digest(plan)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, CanonicalizationError, ValueError):
            print("plan seal: FAIL (plan.json or plan.seal.json is unreadable)")
            failed = True
        else:
            if plan_digest == seal.get("sha256"):
                print(f"plan seal: PASS (sha256={seal['sha256']})")
            else:
                print("plan seal: FAIL (plan.json does not match plan.seal.json)")
                failed = True

    verification_path = out_dir / "verification.json"
    verification_seal_path = out_dir / "verification.seal.json"
    if verification_path.exists() or verification_seal_path.exists():
        if not (verification_path.exists() and verification_seal_path.exists()):
            print("verification seal: FAIL (verification.json and verification.seal.json must both exist)")
            failed = True
        else:
            try:
                verification = _read_json_object(verification_path)
                verification_seal = _read_json_object(verification_seal_path)
                verification_digest = seal_digest(verification)
                verification_ok = verification_digest == verification_seal.get("sha256")
                bound_plan = verification.get("plan_sha256") == verification_seal.get("plan_sha256")
                bound_plan = bound_plan and plan_digest is not None and verification.get("plan_sha256") == plan_digest
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, CanonicalizationError, ValueError):
                print("verification seal: FAIL (verification artifacts are unreadable)")
                failed = True
            else:
                if verification_ok and bound_plan and plan is not None:
                    print(f"verification seal: PASS (sha256={verification_seal['sha256']}; bound to plan)")
                    try:
                        verify_payload(
                            verification,
                            plan,
                            expected_plan_sha256=plan_digest,
                        )
                        print("verification semantics: PASS (contract and human-approval boundary hold)")
                    except VerificationError as error:
                        print(f"verification semantics: FAIL ({error})")
                        failed = True
                else:
                    print("verification seal: FAIL (artifact digest or plan binding does not match)")
                    failed = True

    agent_path = out_dir / "agent_briefing.json"
    agent_seal_path = out_dir / "agent_briefing.seal.json"
    if agent_path.exists() or agent_seal_path.exists():
        if not (agent_path.exists() and agent_seal_path.exists()):
            print("agent briefing seal: FAIL (agent_briefing.json and agent_briefing.seal.json must both exist)")
            failed = True
        elif plan is None or plan_digest is None or verification is None or verification_digest is None:
            print("agent briefing seal: FAIL (verified plan and verification artifacts are required)")
            failed = True
        else:
            from lifeline.agent import AGENT_BRIEFING_VERSION, AGENT_SEAL_VERSION, AgentBriefingError, AgentInputs, verify_agent_artifact
            from lifeline.export import CANONICALIZE_VERSION
            try:
                agent = _read_json_object(agent_path)
                agent_seal = _read_json_object(agent_seal_path)
                agent_ok = seal_digest(agent) == agent_seal.get("sha256")
                binding_ok = (
                    agent.get("plan_sha256") == plan_digest
                    and agent.get("verification_sha256") == verification_digest
                    and agent_seal.get("plan_sha256") == plan_digest
                    and agent_seal.get("verification_sha256") == verification_digest
                    and agent_seal.get("canonicalize_version") == CANONICALIZE_VERSION
                    and agent_seal.get("agent_briefing_version") == AGENT_BRIEFING_VERSION
                    and agent_seal.get("seal_version") == AGENT_SEAL_VERSION
                )
                if not agent_ok or not binding_ok:
                    raise AgentBriefingError("artifact digest or sealed-input binding does not match")
                verify_agent_artifact(agent, AgentInputs(plan, verification, plan_digest, verification_digest))
            except (AgentBriefingError, OSError, UnicodeDecodeError, json.JSONDecodeError, CanonicalizationError, ValueError) as error:
                print(f"agent briefing seal: FAIL ({error})")
                failed = True
            else:
                print(f"agent briefing seal: PASS (sha256={agent_seal['sha256']}; interpretive-only binding holds)")

    sim_path = out_dir / "simulation.json"
    sim_seal_path = out_dir / "simulation.seal.json"
    if sim_path.exists() or sim_seal_path.exists():
        if not (sim_path.exists() and sim_seal_path.exists()):
            print("simulation seal: FAIL (simulation.json and simulation.seal.json must both exist)")
            failed = True
        else:
            try:
                sim = _read_json_object(sim_path)
                sim_seal = _read_json_object(sim_seal_path)
                simulation_ok = seal_digest(sim) == sim_seal.get("sha256")
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, CanonicalizationError, ValueError):
                print("simulation seal: FAIL (simulation artifacts are unreadable)")
                failed = True
            else:
                if simulation_ok:
                    print(f"simulation seal: PASS (sha256={sim_seal['sha256']})")
                else:
                    print("simulation seal: FAIL (simulation.json does not match simulation.seal.json)")
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

    incidents_path = out_dir / "incidents.sqlite3"
    if not incidents_path.exists():
        print("incident ledger: ABSENT (no local incidents recorded)")
    else:
        from lifeline.incidents import IncidentStore, IncidentStoreError
        try:
            count = IncidentStore(incidents_path).verify_all()
            print(f"incident ledger: PASS ({count} incident(s); snapshot and hash-linked event tips agree)")
        except IncidentStoreError as error:
            print(f"incident ledger: FAIL ({error})")
            failed = True

    return 1 if failed else 0


def _read_json_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must be a JSON object")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
