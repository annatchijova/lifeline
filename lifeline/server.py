"""Local incident-room server: static room + append-only approvals API.

Stdlib only. Binds to loopback by design. The incident API requires a local
bearer token issued by ``lifeline operator init``; the authenticated identity,
not a client-supplied name, is written into approvals.

Endpoints:
  GET/POST /api/incidents -> list/search or create validated incidents
  GET    /api/incidents/{id} -> current revision and scenario
  POST   /api/incidents/{id}/reports -> append one validated typed report
  POST   /api/incidents/{id}/corrections -> supersede one report, never silently mutate it
  GET    /api/incidents/{id}/events?after_revision=N -> append-only event feed
  GET    /api/incidents/{id}/alerts?after_revision=N -> deterministic attention feed
  POST   /api/incidents/{id}/plan -> seal a plan from the stored revision
  GET/POST /api/incidents/{id}/approvals -> verified per-incident decision ledger
  GET  /api/approvals   -> {"entries": [...], "chain_ok": bool, "chain_error": str|null}
  POST /api/approvals   -> record one decision for a PROPOSED item of the
                           current sealed plan; 409 on stale plan/proposal
                           or duplicate decision.
Static: / redirects to the bundled synthetic demo. `/web/room.html?mode=live`
renders only the caller's `/out/*` export.
"""

from __future__ import annotations

import json
import os
import posixpath
import stat
import threading
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from lifeline.approvals import ACTIONS, ApprovalChainError, append_entry, read_entries, verify_chain
from lifeline.alerts import alerts_from_events
from lifeline.auth import AuthError, Operator, OperatorStore
from lifeline.export import CanonicalizationError, seal_digest
from lifeline.incidents import IncidentConflict, IncidentNotFound, IncidentStore, IncidentStoreError

MAX_BODY_BYTES = 8192
MAX_FIELD_LENGTH = 200
REQUEST_TIMEOUT_SECONDS = 5.0
PUBLIC_ARTIFACTS = frozenset({
    "plan.json", "plan.seal.json", "verification.json", "verification.seal.json", "room.geojson",
    "simulation.json", "simulation.seal.json", "agent_briefing.json", "agent_briefing.seal.json",
})


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _load_current_plan(out_dir: Path) -> tuple[dict, str]:
    plan_path = out_dir / "plan.json"
    seal_path = out_dir / "plan.seal.json"
    if not plan_path.exists() or not seal_path.exists():
        raise ApiError(404, "no exported plan found; run: python3 -m lifeline plan <scenario> --out out")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
        if not isinstance(plan, dict) or not isinstance(seal, dict):
            raise ValueError("plan and seal must be JSON objects")
        proposals = plan.get("proposals")
        if not isinstance(proposals, list) or any(
            not isinstance(proposal, dict)
            or any(not isinstance(proposal.get(field), str) for field in ("request_id", "status", "audit_hash"))
            for proposal in proposals
        ):
            raise ValueError("plan proposals have an invalid shape")
        recomputed = seal_digest(plan)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, CanonicalizationError, ValueError) as error:
        raise ApiError(500, "exported plan artifacts are unreadable; refusing to record approvals") from error
    if recomputed != seal.get("sha256"):
        raise ApiError(500, "plan.json does not match plan.seal.json; refusing to record approvals")
    return plan, recomputed


class RoomHandler(SimpleHTTPRequestHandler):
    def __init__(self, request, client_address, server, **kwargs):
        super().__init__(request, client_address, server, directory=str(server.root_dir), **kwargs)

    def setup(self):
        self.request.settimeout(self.server.request_timeout_seconds)
        super().setup()

    def log_message(self, format, *args):  # quieter default
        pass

    def _clean_path(self) -> str:
        return posixpath.normpath(urlparse(self.path).path)

    def _json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "Content-Length must be an integer")
        if length <= 0:
            raise ApiError(400, "empty body")
        if length > MAX_BODY_BYTES:
            raise ApiError(413, "body too large")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except TimeoutError:
            raise ApiError(408, "request body timed out")
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ApiError(400, "body must be valid JSON")
        if not isinstance(value, dict):
            raise ApiError(400, "body must be a JSON object")
        return value

    def translate_path(self, path):
        clean = self._clean_path()
        if clean == "/out" or clean.startswith("/out/"):
            relative = clean[len("/out"):].lstrip("/")
            return str(self.server.out_dir / relative)
        return super().translate_path(path)

    def _public_artifact_name(self, clean: str) -> str | None:
        if not clean.startswith("/out/"):
            return None
        artifact = clean.rsplit("/", 1)[-1]
        return artifact if artifact in PUBLIC_ARTIFACTS else None

    def _open_public_artifact(self, artifact: str) -> tuple[int, os.stat_result] | None:
        """Open one allowed artifact without following a symlink.

        Artifact names are an allowlist, but a name alone is not a filesystem
        boundary: a writable out directory could replace a permitted name with
        a symlink or FIFO. On POSIX, O_NOFOLLOW closes the check/open race and
        O_NONBLOCK prevents a FIFO from blocking before fstat rejects it.
        """
        path = self.server.out_dir / artifact
        if path.is_symlink():
            return None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            descriptor = os.open(path, flags)
        except (OSError, ValueError):
            return None
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            os.close(descriptor)
            return None
        return descriptor, info

    def _open_web_file(self, clean: str) -> tuple[int, os.stat_result] | None:
        """Open a static web file without following a symlink at any depth."""
        relative = unquote(clean[len("/web/"):])
        parts = tuple(relative.split("/"))
        if not parts or any(part in {"", ".", ".."} for part in parts):
            return None
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        directory_fd: int | None = None
        try:
            directory_fd = os.open(self.server.root_dir / "web", directory_flags)
            for part in parts[:-1]:
                child_fd = os.open(part, directory_flags, dir_fd=directory_fd)
                os.close(directory_fd)
                directory_fd = child_fd
            descriptor = os.open(parts[-1], file_flags, dir_fd=directory_fd)
        except (OSError, ValueError):
            return None
        finally:
            if directory_fd is not None:
                os.close(directory_fd)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            os.close(descriptor)
            return None
        return descriptor, info

    def _serve_open_file(
        self, opened: tuple[int, os.stat_result] | None, display_path: Path, *, head_only: bool,
    ) -> None:
        if opened is None:
            self.send_error(404, "file is not publicly served")
            return
        descriptor, info = opened
        with os.fdopen(descriptor, "rb") as source:
            self.send_response(200)
            self.send_header("Content-Type", self.guess_type(str(display_path)))
            self.send_header("Content-Length", str(info.st_size))
            self.end_headers()
            if not head_only:
                self.copyfile(source, self.wfile)

    def _serve_public_artifact(self, artifact: str, *, head_only: bool) -> None:
        self._serve_open_file(
            self._open_public_artifact(artifact), self.server.out_dir / artifact, head_only=head_only)

    def _serve_web_file(self, clean: str, *, head_only: bool) -> None:
        relative = unquote(clean[len("/web/"):])
        self._serve_open_file(
            self._open_web_file(clean), self.server.root_dir / "web" / relative, head_only=head_only)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _operator(self, required_role: str) -> Operator:
        authorization = self.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise ApiError(401, "a bearer token is required")
        try:
            operator = self.server.operators.authenticate(token)
        except AuthError as error:
            raise ApiError(401, str(error)) from error
        if not self.server.operators.allows(operator, required_role):
            raise ApiError(403, f"operator '{operator.operator_id}' does not have the '{required_role}' role")
        return operator

    def do_GET(self):
        clean = self._clean_path()
        parsed = urlparse(self.path)
        if clean == "/api/incidents":
            try:
                self._operator("reader")
            except ApiError as error:
                self._send_json(error.status, {"error": error.message})
                return
            query = parse_qs(parsed.query).get("q", [""])[0]
            self._send_json(200, {"incidents": self.server.incidents.list(query)})
            return
        if clean.startswith("/api/incidents/"):
            self._get_incident(clean, parsed.query)
            return
        if clean == "/api/approvals":
            try:
                self._operator("reader")
            except ApiError as error:
                self._send_json(error.status, {"error": error.message})
                return
            entries = []
            chain_error = None
            try:
                entries = read_entries(self.server.approvals_path)
                verify_chain(entries)
            except ApprovalChainError as error:
                chain_error = str(error)
            self._send_json(200, {"entries": entries, "chain_ok": chain_error is None, "chain_error": chain_error})
            return
        if clean == "/":
            self.send_response(302)
            self.send_header("Location", "/web/room.html?mode=demo")
            self.end_headers()
            return
        if clean.startswith("/out/"):
            artifact = self._public_artifact_name(clean)
            if artifact is None:
                self.send_error(404, "artifact is not publicly served")
                return
            self._serve_public_artifact(artifact, head_only=False)
            return
        if clean.startswith("/web/"):
            self._serve_web_file(clean, head_only=False)
            return
        self.send_error(404, "only /web/, selected /out/ artifacts, and /api/ are served")

    def do_HEAD(self):
        clean = self._clean_path()
        if clean.startswith("/out/"):
            artifact = self._public_artifact_name(clean)
            if artifact is None:
                self.send_error(404, "artifact is not publicly served")
                return
            self._serve_public_artifact(artifact, head_only=True)
            return
        if clean.startswith("/web/"):
            self._serve_web_file(clean, head_only=True)
            return
        self.send_error(404, "only /web/ and selected /out/ artifacts are served")

    def do_POST(self):
        clean = self._clean_path()
        if clean == "/api/incidents":
            try:
                self._operator("reporter")
                snapshot = self.server.incidents.create(self._json_body())
            except ApiError as error:
                self._send_json(error.status, {"error": error.message})
                return
            except (IncidentStoreError, IncidentConflict) as error:
                self._send_json(409 if isinstance(error, IncidentConflict) else 400, {"error": str(error)})
                return
            self._send_json(201, self._snapshot_payload(snapshot))
            return
        if clean.startswith("/api/incidents/"):
            self._post_incident(clean)
            return
        if clean != "/api/approvals":
            self.send_error(404)
            return
        try:
            entry = self._record_approval(self._operator("coordinator"))
        except ApiError as error:
            self._send_json(error.status, {"error": error.message})
            return
        self._send_json(201, {"entry": entry})

    def _record_approval(self, operator: Operator) -> dict:
        body = self._json_body()

        fields = {}
        for name in ("request_id", "action", "proposal_audit_hash", "plan_sha256"):
            value = body.get(name)
            if not isinstance(value, str) or not value.strip():
                raise ApiError(400, f"field '{name}' must be a non-empty string")
            if len(value) > MAX_FIELD_LENGTH:
                raise ApiError(400, f"field '{name}' exceeds {MAX_FIELD_LENGTH} characters")
            fields[name] = value.strip()
        declared_approver = body.get("approver")
        if declared_approver is not None and declared_approver != operator.operator_id:
            raise ApiError(403, "client-supplied approver does not match authenticated operator")
        if fields["action"] not in ACTIONS:
            raise ApiError(400, f"action must be one of {list(ACTIONS)}")

        plan, plan_sha = _load_current_plan(self.server.out_dir)
        if fields["plan_sha256"] != plan_sha:
            raise ApiError(409, "stale plan: the room is showing an older export; reload")
        proposal = next((p for p in plan["proposals"] if p["request_id"] == fields["request_id"]), None)
        if proposal is None:
            raise ApiError(409, "unknown request_id for the current plan")
        if proposal["status"] != "PROPOSED":
            raise ApiError(409, "only PROPOSED items accept an approval decision")
        if proposal["audit_hash"] != fields["proposal_audit_hash"]:
            raise ApiError(409, "stale proposal: audit hash does not match the current plan")

        with self.server.approvals_lock:
            try:
                entries = read_entries(self.server.approvals_path)
                verify_chain(entries)
            except ApprovalChainError as error:
                raise ApiError(500, f"approval log failed verification, refusing to append: {error}")
            if any(e["request_id"] == fields["request_id"] and e["plan_sha256"] == plan_sha for e in entries):
                raise ApiError(409, "a decision for this proposal is already recorded")
            try:
                return append_entry(
                    self.server.approvals_path,
                    request_id=fields["request_id"],
                    action=fields["action"],
                    approver=operator.operator_id,
                    proposal_audit_hash=fields["proposal_audit_hash"],
                    plan_sha256=plan_sha,
                    recorded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                )
            except ApprovalChainError as error:
                raise ApiError(400, str(error))

    @staticmethod
    def _snapshot_payload(snapshot) -> dict:
        return {
            "incident_id": snapshot.incident_id,
            "revision": snapshot.revision,
            "scenario_sha256": snapshot.scenario_sha256,
            "updated_at": snapshot.updated_at,
            "scenario": snapshot.scenario,
        }

    @staticmethod
    def _incident_path(clean: str) -> tuple[str, str | None]:
        parts = [part for part in clean.split("/") if part]
        # /api/incidents/{id}[/events|reports|plan]
        if len(parts) not in (3, 4) or parts[:2] != ["api", "incidents"]:
            raise ApiError(404, "unknown incidents endpoint")
        incident_id = unquote(parts[2])
        if not incident_id:
            raise ApiError(404, "incident id is required")
        return incident_id, parts[3] if len(parts) == 4 else None

    def _get_incident(self, clean: str, query: str) -> None:
        try:
            self._operator("reader")
            incident_id, action = self._incident_path(clean)
            if action is None:
                self._send_json(200, self._snapshot_payload(self.server.incidents.get(incident_id)))
                return
            if action == "events":
                raw_after = parse_qs(query).get("after_revision", ["0"])[0]
                try:
                    after_revision = int(raw_after)
                except ValueError:
                    raise ApiError(400, "after_revision must be an integer")
                self._send_json(200, {"incident_id": incident_id, "events": self.server.incidents.events(incident_id, after_revision)})
                return
            if action == "alerts":
                raw_after = parse_qs(query).get("after_revision", ["0"])[0]
                try:
                    after_revision = int(raw_after)
                except ValueError:
                    raise ApiError(400, "after_revision must be an integer")
                events = self.server.incidents.events(incident_id, after_revision)
                self._send_json(200, {"incident_id": incident_id, "alerts": alerts_from_events(events)})
                return
            if action == "approvals":
                entries = self.server.incidents.approvals(incident_id)
                self._send_json(200, {"incident_id": incident_id, "entries": entries, "chain_ok": True})
                return
            raise ApiError(404, "unknown incidents endpoint")
        except IncidentNotFound as error:
            self._send_json(404, {"error": str(error)})
        except IncidentStoreError as error:
            self._send_json(400, {"error": str(error)})
        except ApiError as error:
            self._send_json(error.status, {"error": error.message})

    def _post_incident(self, clean: str) -> None:
        try:
            incident_id, action = self._incident_path(clean)
            if action == "reports":
                self._operator("reporter")
                body = self._json_body()
                entity_type = body.get("entity_type")
                report = body.get("report")
                if not isinstance(entity_type, str):
                    raise ApiError(400, "entity_type must be a string")
                snapshot = self.server.incidents.add_report(incident_id, entity_type, report)
                self._send_json(201, self._snapshot_payload(snapshot))
                return
            if action == "corrections":
                self._operator("coordinator")
                body = self._json_body()
                entity_type = body.get("entity_type")
                report = body.get("report")
                if not isinstance(entity_type, str):
                    raise ApiError(400, "entity_type must be a string")
                snapshot = self.server.incidents.supersede_report(incident_id, entity_type, report)
                self._send_json(201, self._snapshot_payload(snapshot))
                return
            if action == "plan":
                self._operator("reader")
                body = self._json_body()
                reference_time = body.get("reference_time")
                if reference_time is not None and not isinstance(reference_time, str):
                    raise ApiError(400, "reference_time must be a string or null")
                self._send_json(200, self.server.incidents.plan(incident_id, reference_time))
                return
            if action == "approvals":
                operator = self._operator("coordinator")
                body = self._json_body()
                for field in ("request_id", "action", "proposal_audit_hash", "plan_sha256"):
                    if not isinstance(body.get(field), str) or not body[field].strip():
                        raise ApiError(400, f"field '{field}' must be a non-empty string")
                reference_time = body.get("reference_time")
                if reference_time is not None and not isinstance(reference_time, str):
                    raise ApiError(400, "reference_time must be a string or null")
                entry = self.server.incidents.record_approval(
                    incident_id, request_id=body["request_id"].strip(), action=body["action"].strip(),
                    approver=operator.operator_id, proposal_audit_hash=body["proposal_audit_hash"].strip(),
                    plan_sha256=body["plan_sha256"].strip(), reference_time=reference_time,
                )
                self._send_json(201, {"entry": entry})
                return
            raise ApiError(404, "unknown incidents endpoint")
        except IncidentNotFound as error:
            self._send_json(404, {"error": str(error)})
        except IncidentConflict as error:
            self._send_json(409, {"error": str(error)})
        except IncidentStoreError as error:
            self._send_json(400, {"error": str(error)})
        except ApiError as error:
            self._send_json(error.status, {"error": error.message})


def make_server(root_dir: str | Path, out_dir: str | Path, host: str = "127.0.0.1", port: int = 8788) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), RoomHandler)
    server.root_dir = Path(root_dir).resolve()
    server.out_dir = Path(out_dir).resolve()
    server.approvals_path = server.out_dir / "approvals.jsonl"
    server.approvals_lock = threading.Lock()
    server.request_timeout_seconds = REQUEST_TIMEOUT_SECONDS
    server.incidents = IncidentStore(server.out_dir / "incidents.sqlite3")
    server.operators = OperatorStore(server.out_dir / "operators.sqlite3")
    return server


def serve(root_dir: str | Path, out_dir: str | Path, host: str = "127.0.0.1", port: int = 8788) -> None:
    server = make_server(root_dir, out_dir, host, port)
    print(f"incident room: http://{host}:{port}/web/room.html")
    print(f"approvals log: {server.approvals_path} (append-only, hash-chained)")
    print("local use only: bearer-token authentication is required; approver identity comes from the authenticated operator")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
