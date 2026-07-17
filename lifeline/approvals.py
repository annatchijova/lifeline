"""Append-only, hash-chained approval log.

Each entry seals the previous one: entry_hash = SHA-256 over the canonical
encoding of the entry minus its own hash, with prev_hash inside. Verification
detects any altered, inserted, reordered, or dropped interior entry.

Known limitation (documented, not hidden): truncating the tail of the file
is not detectable from the file alone; that requires an external anchor of
the latest entry_hash. Until an anchor exists, treat the chain as proof of
integrity of what is present, not proof of completeness.
"""

from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path

from lifeline.export import canonicalize

GENESIS_HASH = sha256(b"LIFELINE_APPROVALS_GENESIS").hexdigest()
ACTIONS = ("approve", "reject")
ENTRY_FIELDS = (
    "index", "prev_hash", "recorded_at", "request_id", "action",
    "approver", "proposal_audit_hash", "plan_sha256", "entry_hash",
)


class ApprovalChainError(ValueError):
    """The approval log failed validation or verification."""


def _entry_hash(entry: dict) -> str:
    unsealed = {key: value for key, value in entry.items() if key != "entry_hash"}
    return sha256(canonicalize(unsealed)).hexdigest()


def read_entries(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    entries = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as error:
            raise ApprovalChainError(f"line {line_number}: invalid JSON ({error})") from error
        entries.append(entry)
    return entries


def verify_chain(entries: list[dict]) -> None:
    prev_hash = GENESIS_HASH
    for position, entry in enumerate(entries):
        where = f"entry #{position}"
        missing = [field for field in ENTRY_FIELDS if field not in entry]
        if missing:
            raise ApprovalChainError(f"{where}: missing fields {missing}")
        if entry["index"] != position:
            raise ApprovalChainError(f"{where}: index {entry['index']} breaks the sequence")
        if entry["prev_hash"] != prev_hash:
            raise ApprovalChainError(f"{where}: prev_hash does not seal the previous entry")
        if entry["action"] not in ACTIONS:
            raise ApprovalChainError(f"{where}: unknown action '{entry['action']}'")
        if _entry_hash(entry) != entry["entry_hash"]:
            raise ApprovalChainError(f"{where}: entry_hash does not match entry content")
        prev_hash = entry["entry_hash"]


def append_entry(
    path: str | Path,
    *,
    request_id: str,
    action: str,
    approver: str,
    proposal_audit_hash: str,
    plan_sha256: str,
    recorded_at: str,
) -> dict:
    if action not in ACTIONS:
        raise ApprovalChainError(f"unknown action '{action}'")
    for name, value in (
        ("request_id", request_id), ("approver", approver),
        ("proposal_audit_hash", proposal_audit_hash),
        ("plan_sha256", plan_sha256), ("recorded_at", recorded_at),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ApprovalChainError(f"field '{name}' must be a non-empty string")

    entries = read_entries(path)
    verify_chain(entries)
    prev_hash = entries[-1]["entry_hash"] if entries else GENESIS_HASH
    entry = {
        "index": len(entries),
        "prev_hash": prev_hash,
        "recorded_at": recorded_at,
        "request_id": request_id,
        "action": action,
        "approver": approver.strip(),
        "proposal_audit_hash": proposal_audit_hash,
        "plan_sha256": plan_sha256,
    }
    entry["entry_hash"] = _entry_hash(entry)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return entry
