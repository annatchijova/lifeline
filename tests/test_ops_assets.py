from pathlib import Path


def test_operations_console_stays_local_and_does_not_persist_tokens():
    page = (Path(__file__).resolve().parent.parent / "web" / "ops.html").read_text(encoding="utf-8")

    assert "Local operations console" in page
    assert "/api/incidents" in page
    assert "/approvals" in page
    assert "dispatch_authority" in page
    assert "localStorage" not in page
    assert "sessionStorage" not in page


def test_operations_console_labels_agent_briefing_as_optional_and_non_authoritative():
    page = (Path(__file__).resolve().parent.parent / "web" / "ops.html").read_text(encoding="utf-8")

    assert 'id="agent-briefing"' in page
    assert "/agent-briefing" in page
    assert "citationLabel" in page
    assert "incident_changes" in page
    assert "headline_citations" in page
    assert "summary_citations" in page
    assert "verifyAgentSeal" in page
    assert "agent_briefing_seal" in page
    assert "crypto.subtle.digest" in page
    assert "INTERPRETIVE_ONLY" in page
    assert "The provider returns opaque citation selections" in page
    assert "LIFELINE renders every visible sentence locally" in page
