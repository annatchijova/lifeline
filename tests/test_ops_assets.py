from pathlib import Path


def test_operations_console_stays_local_and_does_not_persist_tokens():
    page = (Path(__file__).resolve().parent.parent / "web" / "ops.html").read_text(encoding="utf-8")

    assert "Local operations console" in page
    assert "/api/incidents" in page
    assert "dispatch_authority" in page
    assert "localStorage" not in page
    assert "sessionStorage" not in page
