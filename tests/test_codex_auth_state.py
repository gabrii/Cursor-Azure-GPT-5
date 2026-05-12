"""Unit tests for Codex auth state handling."""

from __future__ import annotations

import base64
import json
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from app.codex.auth_state import (
    REFRESH_URL,
    AuthStateError,
    CodexAuthManager,
    CodexAuthStore,
    decode_jwt_payload,
)


def _jwt(payload):
    def enc(obj):
        raw = json.dumps(obj, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{enc({'alg': 'none'})}.{enc(payload)}.sig"


def _write_auth(
    path,
    *,
    access_exp=None,
    access_token=None,
    refresh_token="refresh",
    account_id="acct_1",
    extra=None,
):
    raw = {
        "auth_mode": "chatgpt",
        "tokens": {
            "id_token": _jwt(
                {
                    "https://api.openai.com/auth": {
                        "chatgpt_account_id": account_id,
                    }
                }
            ),
            "access_token": access_token
            or _jwt({"exp": access_exp or int(time.time()) + 3600}),
            "refresh_token": refresh_token,
            "account_id": account_id,
        },
    }
    if extra:
        raw.update(extra)
    path.write_text(json.dumps(raw))


def test_codex_decode_jwt_payload_handles_urlsafe_padding():
    """JWT decoding handles unpadded URL-safe payloads."""
    token = _jwt({"exp": 123, "nested": {"ok": True}})

    assert decode_jwt_payload(token)["nested"]["ok"] is True


def test_codex_auth_store_loads_codex_auth_json(tmp_path):
    """Codex auth store loads ChatGPT tokens and account claims."""
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "id_token": _jwt(
                        {
                            "https://api.openai.com/auth": {
                                "chatgpt_account_id": "acct_1",
                                "chatgpt_account_is_fedramp": True,
                            }
                        }
                    ),
                    "access_token": _jwt({"exp": int(time.time()) + 3600}),
                    "refresh_token": "refresh",
                    "account_id": "acct_1",
                },
            }
        )
    )

    state = CodexAuthStore(auth_file).load()

    assert state.access_token
    assert state.refresh_token == "refresh"
    assert state.account_id == "acct_1"
    assert state.fedramp is True
    assert state.is_expired(skew_seconds=60) is False


def test_codex_auth_store_requires_chatgpt_tokens(tmp_path):
    """API-key auth state is rejected."""
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({"auth_mode": "api_key"}))

    with pytest.raises(AuthStateError, match="ChatGPT"):
        CodexAuthStore(auth_file).load()


def test_codex_auth_store_validate_ready_uses_real_file_access(tmp_path, monkeypatch):
    """Readiness should rely on real file access, not os.access false negatives."""
    auth_file = tmp_path / "auth.json"
    _write_auth(auth_file)

    def fake_access(path, mode):
        return False if Path(path) == auth_file else True

    monkeypatch.setattr("app.codex.auth_state.os.access", fake_access)

    CodexAuthStore(auth_file).validate_ready()


def test_codex_auth_manager_skips_refresh_after_locked_reload(tmp_path, monkeypatch):
    """If another local worker refreshed first, do not reuse the old refresh token."""
    auth_file = tmp_path / "auth.json"
    _write_auth(
        auth_file,
        access_exp=int(time.time()) - 3600,
        refresh_token="old-refresh",
    )
    store = CodexAuthStore(auth_file)

    @contextmanager
    def fake_refresh_lock():
        _write_auth(auth_file, refresh_token="new-refresh")
        yield

    monkeypatch.setattr(store, "refresh_lock", fake_refresh_lock)
    monkeypatch.setattr(
        "app.codex.auth_state.requests.post",
        lambda *args, **kwargs: pytest.fail("refresh token must not be reused"),
    )

    state = CodexAuthManager(store, refresh_skew_seconds=300).current()

    assert state.refresh_token == "new-refresh"
    assert state.is_expired(skew_seconds=300) is False


def test_codex_auth_manager_refreshes_expired_token(tmp_path, monkeypatch):
    """Expired tokens are refreshed and unrelated auth state is preserved."""
    auth_file = tmp_path / "auth.json"
    _write_auth(
        auth_file,
        access_exp=int(time.time()) - 3600,
        refresh_token="old-refresh",
        extra={"custom_field": "keep-me"},
    )
    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "id_token": _jwt({"exp": int(time.time()) + 3600}),
                "access_token": _jwt({"exp": int(time.time()) + 3600}),
                "refresh_token": "new-refresh",
            }

    def fake_post(url, headers, json, timeout):
        captured.update(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return FakeResponse()

    monkeypatch.setattr("app.codex.auth_state.requests.post", fake_post)

    state = CodexAuthManager(
        CodexAuthStore(auth_file), refresh_skew_seconds=300
    ).current()
    raw = json.loads(auth_file.read_text())

    assert captured["url"] == REFRESH_URL
    assert captured["json"]["refresh_token"] == "old-refresh"
    assert state.refresh_token == "new-refresh"
    assert raw["custom_field"] == "keep-me"
    assert raw["last_refresh"]


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("refresh_token_expired", "expired"),
        ("refresh_token_reused", "already used"),
        ("refresh_token_invalidated", "revoked"),
    ],
)
def test_codex_auth_manager_reports_known_refresh_401_codes(
    tmp_path, monkeypatch, code, message
):
    """Known single-use refresh-token failures get actionable messages."""
    auth_file = tmp_path / "auth.json"
    _write_auth(auth_file, access_exp=int(time.time()) - 3600)

    class FakeResponse:
        status_code = 401

        def json(self):
            return {"error": {"code": code}}

    monkeypatch.setattr(
        "app.codex.auth_state.requests.post",
        lambda *args, **kwargs: FakeResponse(),
    )

    with pytest.raises(AuthStateError, match=message):
        CodexAuthManager(CodexAuthStore(auth_file), refresh_skew_seconds=300).current()


def test_codex_auth_manager_rejects_malformed_refresh_json(tmp_path, monkeypatch):
    """Malformed refresh responses become local AuthStateError failures."""
    auth_file = tmp_path / "auth.json"
    _write_auth(auth_file, access_exp=int(time.time()) - 3600)

    class FakeResponse:
        status_code = 200

        def json(self):
            raise ValueError("bad json")

    monkeypatch.setattr(
        "app.codex.auth_state.requests.post",
        lambda *args, **kwargs: FakeResponse(),
    )

    with pytest.raises(AuthStateError, match="invalid JSON"):
        CodexAuthManager(CodexAuthStore(auth_file), refresh_skew_seconds=300).current()


def test_codex_auth_manager_rejects_refresh_without_access_token(tmp_path, monkeypatch):
    """Refresh responses must contain a replacement access token."""
    auth_file = tmp_path / "auth.json"
    _write_auth(auth_file, access_exp=int(time.time()) - 3600)

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"refresh_token": "new-refresh"}

    monkeypatch.setattr(
        "app.codex.auth_state.requests.post",
        lambda *args, **kwargs: FakeResponse(),
    )

    with pytest.raises(AuthStateError, match="access token"):
        CodexAuthManager(CodexAuthStore(auth_file), refresh_skew_seconds=300).current()
