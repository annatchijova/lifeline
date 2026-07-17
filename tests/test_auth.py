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
