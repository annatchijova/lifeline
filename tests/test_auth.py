import threading

import pytest

from lifeline.auth import AuthError, OperatorStore


def test_bootstrap_is_one_time_and_tokens_are_not_plaintext(tmp_path):
    store = OperatorStore(tmp_path / "operators.sqlite3")
    admin, token = store.bootstrap("anna-admin")

    assert admin.role == "admin"
    assert store.authenticate(token) == admin
    assert token.encode() not in (tmp_path / "operators.sqlite3").read_bytes()
    with pytest.raises(AuthError, match="already exists"):
        store.bootstrap("another-admin")


def test_admin_can_provision_limited_role_and_role_is_enforced(tmp_path):
    store = OperatorStore(tmp_path / "operators.sqlite3")
    admin, _ = store.bootstrap("admin")
    reporter, reporter_token = store.add(admin, "field-reporter", "reporter")

    assert store.authenticate(reporter_token) == reporter
    assert store.allows(reporter, "reader")
    assert store.allows(reporter, "reporter")
    assert not store.allows(reporter, "coordinator")
    with pytest.raises(AuthError, match="only an admin"):
        store.add(reporter, "other", "reader")


def test_bootstrap_serializes_two_initialization_attempts(tmp_path):
    class GatedConnection:
        def __init__(self, connection, observed, release):
            self.connection = connection
            self.observed = observed
            self.release = release

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            return self.connection.__exit__(*args)

        def execute(self, sql, *args):
            result = self.connection.execute(sql, *args)
            if sql.startswith("SELECT 1 FROM operators LIMIT 1"):
                self.observed.set()
                assert self.release.wait(timeout=5)
            return result

    path = tmp_path / "operators.sqlite3"
    first = OperatorStore(path)
    second = OperatorStore(path)
    observed = threading.Event()
    release = threading.Event()
    second_finished = threading.Event()
    original_connect = first._connect
    first._connect = lambda: GatedConnection(original_connect(), observed, release)
    results = []
    errors = []

    def bootstrap(store, operator_id, done=None):
        try:
            results.append(store.bootstrap(operator_id)[0])
        except AuthError as error:
            errors.append(error)
        finally:
            if done is not None:
                done.set()

    first_thread = threading.Thread(target=bootstrap, args=(first, "admin-one"))
    second_thread = threading.Thread(target=bootstrap, args=(second, "admin-two", second_finished))
    first_thread.start()
    assert observed.wait(timeout=5)
    second_thread.start()
    try:
        # With BEGIN IMMEDIATE, the second bootstrap is blocked before it can
        # observe the empty registry. Without it, this call completes and two
        # distinct initial admins are created.
        assert not second_finished.wait(timeout=1)
    finally:
        release.set()
    first_thread.join(timeout=10)
    second_thread.join(timeout=10)

    assert len(results) == 1
    assert len(errors) == 1
    assert "already exists" in str(errors[0])
    assert OperatorStore(path).has_active_operator()
