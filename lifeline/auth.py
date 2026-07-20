"""Local operator authentication for the loopback coordination server.

Tokens are deliberately local bootstrap credentials, not a substitute for an
organization's identity provider.  Only their scrypt-derived verifier is
stored.  The plaintext token is shown once by the CLI and must be kept in a
secure local secret store by the operator.
"""

from __future__ import annotations

import hmac
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import scrypt
from pathlib import Path


ROLES = ("reader", "reporter", "coordinator", "admin")
_ROLE_LEVEL = {role: index for index, role in enumerate(ROLES)}
_OPERATOR_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_SALT_BYTES = 16
_TOKEN_BYTES = 32


class AuthError(ValueError):
    """Authentication or authorization could not be completed."""


@dataclass(frozen=True)
class Operator:
    operator_id: str
    role: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate_operator_id(operator_id: str) -> str:
    if not isinstance(operator_id, str) or not _OPERATOR_ID.fullmatch(operator_id):
        raise AuthError("operator id must use 1-64 lowercase letters, digits, '-' or '_'")
    return operator_id


def _token_hash(token: str, salt: bytes) -> bytes:
    if not isinstance(token, str) or len(token) < 24:
        raise AuthError("token is invalid")
    return scrypt(token.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)


class OperatorStore:
    """SQLite-backed local operator registry with revocable token verifiers."""

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
            conn.execute(
                """CREATE TABLE IF NOT EXISTS operators (
                    operator_id TEXT PRIMARY KEY,
                    role TEXT NOT NULL,
                    salt BLOB NOT NULL,
                    token_hash BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT
                )"""
            )

    def has_active_operator(self) -> bool:
        with self._connect() as conn:
            return conn.execute("SELECT 1 FROM operators WHERE revoked_at IS NULL LIMIT 1").fetchone() is not None

    def _create(self, operator_id: str, role: str) -> tuple[Operator, str, bytes, bytes]:
        operator_id = _validate_operator_id(operator_id)
        if role not in ROLES:
            raise AuthError(f"role must be one of {list(ROLES)}")
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        salt = secrets.token_bytes(_SALT_BYTES)
        verifier = _token_hash(token, salt)
        return Operator(operator_id, role), token, salt, verifier

    def bootstrap(self, operator_id: str, role: str = "admin") -> tuple[Operator, str]:
        """Create the initial local admin exactly once and return its plaintext token."""
        if role != "admin":
            raise AuthError("the initial operator must be an admin")
        operator, token, salt, verifier = self._create(operator_id, role)
        with self._connect() as conn:
            # The empty-registry observation and first insert are one critical
            # section. This prevents two local bootstrap processes from both
            # creating an initial administrator.
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM operators LIMIT 1").fetchone() is not None:
                raise AuthError("an operator registry already exists; bootstrap is refused")
            conn.execute(
                "INSERT INTO operators VALUES (?, ?, ?, ?, ?, NULL)",
                (operator.operator_id, operator.role, salt, verifier, _now()),
            )
        return operator, token

    def add(self, authorizer: Operator, operator_id: str, role: str) -> tuple[Operator, str]:
        """Create a local operator after a separately authenticated admin check."""
        if not self.allows(authorizer, "admin"):
            raise AuthError("only an admin may add a local operator")
        operator, token, salt, verifier = self._create(operator_id, role)
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO operators VALUES (?, ?, ?, ?, ?, NULL)",
                    (operator.operator_id, operator.role, salt, verifier, _now()),
                )
            except sqlite3.IntegrityError as error:
                raise AuthError(f"operator '{operator.operator_id}' already exists") from error
        return operator, token

    def authenticate(self, token: str) -> Operator:
        if not isinstance(token, str) or not token:
            raise AuthError("missing bearer token")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT operator_id, role, salt, token_hash FROM operators WHERE revoked_at IS NULL"
            ).fetchall()
        for row in rows:
            candidate = _token_hash(token, bytes(row["salt"]))
            if hmac.compare_digest(candidate, bytes(row["token_hash"])):
                return Operator(row["operator_id"], row["role"])
        raise AuthError("invalid bearer token")

    @staticmethod
    def allows(operator: Operator, required_role: str) -> bool:
        if required_role not in _ROLE_LEVEL:
            raise AuthError(f"unknown required role '{required_role}'")
        return _ROLE_LEVEL[operator.role] >= _ROLE_LEVEL[required_role]
