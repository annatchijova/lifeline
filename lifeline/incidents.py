"""Local, append-only incident state for the Lifeline coordination backend.

This is deliberately a loopback-first store.  It accepts only complete,
schema-v1 scenarios at creation and typed additions afterwards.  Every write
validates the resulting scenario before it becomes the next revision, so an
invalid report cannot leave a half-mutated incident behind.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from lifeline.export import plan_payload, seal_digest
from lifeline.scenario import ScenarioError, parse_scenario, plan_scenario
from lifeline.validators import validate_scenario


ENTITY_COLLECTIONS = {
    "request": ("requests", "request_id"),
    "resource": ("resources", "resource_id"),
    "shelter": ("shelters", "shelter_id"),
    "route": ("routes", None),
}
GENESIS_EVENT_HASH = sha256(b"LIFELINE_INCIDENT_EVENTS_GENESIS").hexdigest()


class IncidentStoreError(ValueError):
    """An incident-store operation could not be completed safely."""


class IncidentNotFound(IncidentStoreError):
    """The requested incident does not exist."""


class IncidentConflict(IncidentStoreError):
    """A write would duplicate an existing incident or entity."""


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise IncidentStoreError(f"value is not JSON-safe: {error}") from error


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _route_id(report: dict) -> str:
    origin = report.get("origin")
    destination = report.get("destination")
    if not isinstance(origin, str) or not isinstance(destination, str):
        raise IncidentStoreError("route report requires string origin and destination")
    return f"{origin}->{destination}"


@dataclass(frozen=True)
class IncidentSnapshot:
    incident_id: str
    revision: int
    scenario: dict
    scenario_sha256: str
    updated_at: str


class IncidentStore:
    """SQLite-backed incident snapshots plus a hash-linked mutation ledger."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS incidents (
                    incident_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL,
                    scenario_json TEXT NOT NULL,
                    scenario_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS incident_events (
                    incident_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    scenario_sha256 TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    PRIMARY KEY (incident_id, revision),
                    UNIQUE (event_hash)
                )
            """)

    def _snapshot(self, conn: sqlite3.Connection, incident_id: str) -> IncidentSnapshot:
        row = conn.execute(
            "SELECT incident_id, revision, scenario_json, scenario_sha256, updated_at FROM incidents WHERE incident_id = ?",
            (incident_id,),
        ).fetchone()
        if row is None:
            raise IncidentNotFound(f"incident '{incident_id}' was not found")
        scenario = json.loads(row["scenario_json"])
        if _digest(scenario) != row["scenario_sha256"]:
            raise IncidentStoreError(f"incident '{incident_id}' snapshot hash does not match its stored scenario")
        return IncidentSnapshot(
            incident_id=row["incident_id"],
            revision=row["revision"],
            scenario=scenario,
            scenario_sha256=row["scenario_sha256"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _validate(raw: dict) -> str:
        scenario = parse_scenario(raw)
        return scenario.scenario_id

    @staticmethod
    def _event_hash(event: dict) -> str:
        return _digest(event)

    def _verify_events(self, conn: sqlite3.Connection, incident_id: str) -> None:
        rows = conn.execute(
            """SELECT revision, event_type, entity_type, entity_id, submitted_at, payload_json,
                      scenario_sha256, prev_hash, event_hash
               FROM incident_events WHERE incident_id = ? ORDER BY revision""",
            (incident_id,),
        ).fetchall()
        expected_prev = GENESIS_EVENT_HASH
        for expected_revision, row in enumerate(rows, start=1):
            if row["revision"] != expected_revision:
                raise IncidentStoreError(f"incident '{incident_id}' event revision sequence is broken")
            if row["prev_hash"] != expected_prev:
                raise IncidentStoreError(f"incident '{incident_id}' event chain is broken")
            event = {
                "incident_id": incident_id,
                "revision": row["revision"],
                "event_type": row["event_type"],
                "entity_type": row["entity_type"],
                "entity_id": row["entity_id"],
                "submitted_at": row["submitted_at"],
                "payload": json.loads(row["payload_json"]),
                "scenario_sha256": row["scenario_sha256"],
                "prev_hash": row["prev_hash"],
            }
            if self._event_hash(event) != row["event_hash"]:
                raise IncidentStoreError(f"incident '{incident_id}' event hash does not match its content")
            expected_prev = row["event_hash"]

    def _verified_snapshot(self, conn: sqlite3.Connection, incident_id: str) -> IncidentSnapshot:
        """Return a snapshot only when it is the state sealed by the ledger tip."""
        snapshot = self._snapshot(conn, incident_id)
        self._verify_events(conn, incident_id)
        tip = conn.execute(
            """SELECT revision, scenario_sha256 FROM incident_events
               WHERE incident_id = ? ORDER BY revision DESC LIMIT 1""",
            (incident_id,),
        ).fetchone()
        if tip is None:
            raise IncidentStoreError(f"incident '{incident_id}' has no creation event")
        if tip["revision"] != snapshot.revision:
            raise IncidentStoreError(f"incident '{incident_id}' snapshot revision is not the ledger tip")
        if tip["scenario_sha256"] != snapshot.scenario_sha256:
            raise IncidentStoreError(f"incident '{incident_id}' snapshot hash is not sealed by the ledger tip")
        return snapshot

    def _append_event(
        self,
        conn: sqlite3.Connection,
        *,
        incident_id: str,
        revision: int,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: dict,
        scenario_sha256: str,
        submitted_at: str,
    ) -> dict:
        previous = conn.execute(
            "SELECT event_hash FROM incident_events WHERE incident_id = ? ORDER BY revision DESC LIMIT 1",
            (incident_id,),
        ).fetchone()
        prev_hash = previous["event_hash"] if previous else GENESIS_EVENT_HASH
        event = {
            "incident_id": incident_id,
            "revision": revision,
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "submitted_at": submitted_at,
            "payload": payload,
            "scenario_sha256": scenario_sha256,
            "prev_hash": prev_hash,
        }
        event_hash = self._event_hash(event)
        conn.execute(
            """INSERT INTO incident_events
               (incident_id, revision, event_type, entity_type, entity_id, submitted_at,
                payload_json, scenario_sha256, prev_hash, event_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (incident_id, revision, event_type, entity_type, entity_id, submitted_at,
             _canonical_json(payload), scenario_sha256, prev_hash, event_hash),
        )
        return {**event, "event_hash": event_hash}

    def create(self, raw: dict) -> IncidentSnapshot:
        if not isinstance(raw, dict):
            raise IncidentStoreError("incident payload must be an object")
        try:
            incident_id = self._validate(raw)
        except ScenarioError as error:
            raise IncidentStoreError(str(error)) from error
        now = _utc_now()
        encoded = _canonical_json(raw)
        digest = _digest(raw)
        with self._connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT INTO incidents VALUES (?, ?, ?, ?, ?, ?)",
                    (incident_id, 1, encoded, digest, now, now),
                )
            except sqlite3.IntegrityError as error:
                raise IncidentConflict(f"incident '{incident_id}' already exists") from error
            self._append_event(
                conn, incident_id=incident_id, revision=1, event_type="incident_created",
                entity_type="incident", entity_id=incident_id,
                payload={"scenario_id": incident_id}, scenario_sha256=digest, submitted_at=now,
            )
            return self._snapshot(conn, incident_id)

    def list(self, query: str = "") -> list[dict]:
        clause = ""
        params: tuple[object, ...] = ()
        if query:
            clause = "WHERE incident_id LIKE ?"
            params = (f"%{query}%",)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT incident_id, revision, scenario_sha256, updated_at FROM incidents {clause} ORDER BY updated_at DESC, incident_id",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, incident_id: str) -> IncidentSnapshot:
        with self._connect() as conn:
            return self._verified_snapshot(conn, incident_id)

    def verify_all(self) -> int:
        """Verify every incident's snapshot, event chain, and ledger-tip linkage."""
        with self._connect() as conn:
            incident_ids = [row["incident_id"] for row in conn.execute("SELECT incident_id FROM incidents ORDER BY incident_id")]
            for incident_id in incident_ids:
                self._verified_snapshot(conn, incident_id)
        return len(incident_ids)

    def add_report(self, incident_id: str, entity_type: str, report: dict) -> IncidentSnapshot:
        if entity_type not in ENTITY_COLLECTIONS:
            raise IncidentStoreError(f"unknown entity_type '{entity_type}'")
        if not isinstance(report, dict):
            raise IncidentStoreError("report must be an object")
        collection, id_field = ENTITY_COLLECTIONS[entity_type]
        entity_id = _route_id(report) if id_field is None else report.get(id_field)
        if not isinstance(entity_id, str) or not entity_id.strip():
            raise IncidentStoreError(f"{entity_type} report requires non-empty '{id_field}'")

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            snapshot = self._verified_snapshot(conn, incident_id)
            updated = json.loads(_canonical_json(snapshot.scenario))
            entries = updated.get(collection)
            if not isinstance(entries, list):
                raise IncidentStoreError(f"incident has invalid '{collection}' collection")
            if entity_type != "route" and any(entry.get(id_field) == entity_id for entry in entries):
                raise IncidentConflict(f"{entity_type} '{entity_id}' already exists; additions never overwrite reports")
            if entity_type == "route" and any(_route_id(entry) == entity_id for entry in entries):
                raise IncidentConflict(f"route '{entity_id}' already exists; additions never overwrite reports")
            entries.append(report)
            try:
                self._validate(updated)
            except ScenarioError as error:
                raise IncidentStoreError(str(error)) from error
            now = _utc_now()
            revision = snapshot.revision + 1
            digest = _digest(updated)
            conn.execute(
                "UPDATE incidents SET revision = ?, scenario_json = ?, scenario_sha256 = ?, updated_at = ? WHERE incident_id = ?",
                (revision, _canonical_json(updated), digest, now, incident_id),
            )
            self._append_event(
                conn, incident_id=incident_id, revision=revision, event_type="report_added",
                entity_type=entity_type, entity_id=entity_id, payload=report,
                scenario_sha256=digest, submitted_at=now,
            )
            return self._snapshot(conn, incident_id)

    def supersede_report(self, incident_id: str, entity_type: str, report: dict) -> IncidentSnapshot:
        """Replace one operational report while preserving the prior event forever.

        A correction is intentionally not an update endpoint: it is a new
        ledger event whose replacement becomes the current planning snapshot.
        The previous report remains recoverable from its original event.
        """
        if entity_type not in ENTITY_COLLECTIONS:
            raise IncidentStoreError(f"unknown entity_type '{entity_type}'")
        if not isinstance(report, dict):
            raise IncidentStoreError("report must be an object")
        collection, id_field = ENTITY_COLLECTIONS[entity_type]
        entity_id = _route_id(report) if id_field is None else report.get(id_field)
        if not isinstance(entity_id, str) or not entity_id.strip():
            raise IncidentStoreError(f"{entity_type} report requires non-empty '{id_field}'")

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            snapshot = self._verified_snapshot(conn, incident_id)
            updated = json.loads(_canonical_json(snapshot.scenario))
            entries = updated.get(collection)
            if not isinstance(entries, list):
                raise IncidentStoreError(f"incident has invalid '{collection}' collection")
            matching = [
                index for index, entry in enumerate(entries)
                if (_route_id(entry) if entity_type == "route" else entry.get(id_field)) == entity_id
            ]
            if len(matching) != 1:
                raise IncidentStoreError(f"cannot supersede {entity_type} '{entity_id}': expected exactly one current report")
            previous = entries[matching[0]]
            entries[matching[0]] = report
            try:
                self._validate(updated)
            except ScenarioError as error:
                raise IncidentStoreError(str(error)) from error
            now = _utc_now()
            revision = snapshot.revision + 1
            digest = _digest(updated)
            conn.execute(
                "UPDATE incidents SET revision = ?, scenario_json = ?, scenario_sha256 = ?, updated_at = ? WHERE incident_id = ?",
                (revision, _canonical_json(updated), digest, now, incident_id),
            )
            self._append_event(
                conn, incident_id=incident_id, revision=revision, event_type="report_superseded",
                entity_type=entity_type, entity_id=entity_id,
                payload={"replaces_revision": snapshot.revision, "previous": previous, "replacement": report},
                scenario_sha256=digest, submitted_at=now,
            )
            return self._snapshot(conn, incident_id)

    def events(self, incident_id: str, after_revision: int = 0) -> list[dict]:
        if after_revision < 0:
            raise IncidentStoreError("after_revision must be zero or positive")
        with self._connect() as conn:
            self._verified_snapshot(conn, incident_id)
            rows = conn.execute(
                """SELECT revision, event_type, entity_type, entity_id, submitted_at, payload_json,
                          scenario_sha256, prev_hash, event_hash
                   FROM incident_events WHERE incident_id = ? AND revision > ? ORDER BY revision""",
                (incident_id, after_revision),
            ).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload_json"])} for row in rows]

    def plan(self, incident_id: str, reference_time: str | None = None) -> dict:
        with self._connect() as conn:
            snapshot = self._verified_snapshot(conn, incident_id)
        try:
            scenario, findings = validate_scenario(parse_scenario(snapshot.scenario), reference_time)
        except ScenarioError as error:
            raise IncidentStoreError(str(error)) from error
        proposals = plan_scenario(scenario)
        payload = plan_payload(scenario, proposals, findings, reference_time)
        return {
            "incident_id": incident_id,
            "revision": snapshot.revision,
            "scenario_sha256": snapshot.scenario_sha256,
            "plan": payload,
            "seal": {
                "sha256": seal_digest(payload),
                "plan_version": payload["plan_version"],
            },
        }
