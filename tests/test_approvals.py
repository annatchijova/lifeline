import json

import pytest

from lifeline.approvals import (
    ApprovalChainError,
    GENESIS_HASH,
    append_entry,
    read_entries,
    verify_chain,
)


def _append(path, index, request_id="family-north", action="approve"):
    return append_entry(
        path,
        request_id=request_id,
        action=action,
        approver="coordinator-1",
        proposal_audit_hash=f"hash-{index}",
        plan_sha256="plan-digest",
        recorded_at="2026-07-17T10:00:00+00:00",
    )


def test_chain_appends_and_verifies(tmp_path):
    log = tmp_path / "approvals.jsonl"
    first = _append(log, 0)
    second = _append(log, 1, request_id="family-east", action="reject")
    assert first["prev_hash"] == GENESIS_HASH
    assert second["prev_hash"] == first["entry_hash"]
    entries = read_entries(log)
    verify_chain(entries)
    assert [e["index"] for e in entries] == [0, 1]


def test_tampered_entry_is_detected(tmp_path):
    log = tmp_path / "approvals.jsonl"
    _append(log, 0)
    _append(log, 1, request_id="family-east")
    lines = log.read_text().splitlines()
    entry = json.loads(lines[0])
    entry["approver"] = "someone-else"
    log.write_text("\n".join([json.dumps(entry, sort_keys=True, separators=(",", ":"))] + lines[1:]) + "\n")
    with pytest.raises(ApprovalChainError, match="entry_hash"):
        verify_chain(read_entries(log))


def test_reordered_entries_are_detected(tmp_path):
    log = tmp_path / "approvals.jsonl"
    _append(log, 0)
    _append(log, 1, request_id="family-east")
    lines = log.read_text().splitlines()
    log.write_text("\n".join([lines[1], lines[0]]) + "\n")
    with pytest.raises(ApprovalChainError):
        verify_chain(read_entries(log))


def test_dropped_interior_entry_is_detected(tmp_path):
    log = tmp_path / "approvals.jsonl"
    _append(log, 0)
    _append(log, 1, request_id="family-east")
    _append(log, 2, request_id="group-riverside", action="reject")
    lines = log.read_text().splitlines()
    log.write_text("\n".join([lines[0], lines[2]]) + "\n")
    with pytest.raises(ApprovalChainError):
        verify_chain(read_entries(log))


def test_rejects_bad_action_and_empty_fields(tmp_path):
    log = tmp_path / "approvals.jsonl"
    with pytest.raises(ApprovalChainError, match="unknown action"):
        _append(log, 0, action="dispatch")
    with pytest.raises(ApprovalChainError, match="approver"):
        append_entry(
            log, request_id="x", action="approve", approver="  ",
            proposal_audit_hash="h", plan_sha256="p", recorded_at="t",
        )
