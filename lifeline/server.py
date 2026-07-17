"""Local incident-room server: static room + append-only approvals API.

Stdlib only. Binds to loopback by design; there is no authentication yet,
so this must not be exposed beyond the coordinator's machine. The approver
field is a declared identity, not a verified one — a documented limitation
until roles land (roadmap step 3).

Endpoints:
  GET  /api/approvals   -> {"entries": [...], "chain_ok": bool, "chain_error": str|null}
  POST /api/approvals   -> record one decision for a PROPOSED item of the
                           current sealed plan; 409 on stale plan/proposal
                           or duplicate decision.
Static: / redirects to /web/room.html; only /web/* and /out/* are served.
"""

from __future__ import annotations

import json
import posixpath
import threading
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from lifeline.approvals import ACTIONS, ApprovalChainError, append_entry, read_entries, verify_chain
from lifeline.export import seal_digest

MAX_BODY_BYTES = 8192
MAX_FIELD_LENGTH = 200


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
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    recomputed = seal_digest(plan)
    if recomputed != seal.get("sha256"):
        raise ApiError(500, "plan.json does not match plan.seal.json; refusing to record approvals")
    return plan, recomputed


class RoomHandler(SimpleHTTPRequestHandler):
    def __init__(self, request, client_address, server, **kwargs):
        super().__init__(request, client_address, server, directory=str(server.root_dir), **kwargs)

    def log_message(self, format, *args):  # quieter default
        pass

    def _clean_path(self) -> str:
        return posixpath.normpath(urlparse(self.path).path)

    def translate_path(self, path):
        clean = self._clean_path()
        if clean == "/out" or clean.startswith("/out/"):
            relative = clean[len("/out"):].lstrip("/")
            return str(self.server.out_dir / relative)
        return super().translate_path(path)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        clean = self._clean_path()
        if clean == "/api/approvals":
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
            self.send_header("Location", "/web/room.html")
            self.end_headers()
            return
        if clean == "/web" or clean.startswith("/web/") or clean.startswith("/out/"):
            super().do_GET()
            return
        self.send_error(404, "only /web/, /out/, and /api/approvals are served")

    def do_POST(self):
        if self._clean_path() != "/api/approvals":
            self.send_error(404)
            return
        try:
            entry = self._record_approval()
        except ApiError as error:
            self._send_json(error.status, {"error": error.message})
            return
        self._send_json(201, {"entry": entry})

    def _record_approval(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise ApiError(400, "empty body")
        if length > MAX_BODY_BYTES:
            raise ApiError(413, "body too large")
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ApiError(400, "body must be valid JSON")
        if not isinstance(body, dict):
            raise ApiError(400, "body must be a JSON object")

        fields = {}
        for name in ("request_id", "action", "approver", "proposal_audit_hash", "plan_sha256"):
            value = body.get(name)
            if not isinstance(value, str) or not value.strip():
                raise ApiError(400, f"field '{name}' must be a non-empty string")
            if len(value) > MAX_FIELD_LENGTH:
                raise ApiError(400, f"field '{name}' exceeds {MAX_FIELD_LENGTH} characters")
            fields[name] = value.strip()
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
                    approver=fields["approver"],
                    proposal_audit_hash=fields["proposal_audit_hash"],
                    plan_sha256=plan_sha,
                    recorded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                )
            except ApprovalChainError as error:
                raise ApiError(400, str(error))


def make_server(root_dir: str | Path, out_dir: str | Path, host: str = "127.0.0.1", port: int = 8788) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), RoomHandler)
    server.root_dir = Path(root_dir).resolve()
    server.out_dir = Path(out_dir).resolve()
    server.approvals_path = server.out_dir / "approvals.jsonl"
    server.approvals_lock = threading.Lock()
    return server


def serve(root_dir: str | Path, out_dir: str | Path, host: str = "127.0.0.1", port: int = 8788) -> None:
    server = make_server(root_dir, out_dir, host, port)
    print(f"incident room: http://{host}:{port}/web/room.html")
    print(f"approvals log: {server.approvals_path} (append-only, hash-chained)")
    print("local use only: no authentication; approver identity is declared, not verified")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
