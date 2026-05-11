"""Unit tests for Codex upstream headers."""

from app.codex.auth_state import CodexAuthState
from app.codex.upstream import build_upstream_headers


class Settings:
    """Minimal settings object for upstream header tests."""

    originator = "codex_cli_rs"
    user_agent = "test-agent"


def test_codex_upstream_headers_drop_cursor_auth_and_add_codex_identity():
    """Upstream headers use Codex auth and ignore Cursor credentials."""
    auth = CodexAuthState(
        raw={},
        access_token="access",
        refresh_token="refresh",
        account_id="acct_1",
        access_expires_at=None,
        fedramp=False,
    )

    headers = build_upstream_headers(
        Settings(),
        auth,
        session_id="sess-1",
        thread_id="thread-1",
        downstream_headers={"Authorization": "Bearer cursor", "Cookie": "bad"},
    )

    assert headers["Authorization"] == "Bearer access"
    assert headers["ChatGPT-Account-Id"] == "acct_1"
    assert headers["originator"] == "codex_cli_rs"
    assert headers["session_id"] == "sess-1"
    assert headers["session-id"] == "sess-1"
    assert headers["thread_id"] == "thread-1"
    assert headers["thread-id"] == "thread-1"
    assert "Cookie" not in headers
