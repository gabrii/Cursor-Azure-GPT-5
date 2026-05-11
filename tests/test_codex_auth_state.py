"""Unit tests for Codex auth state handling."""

from __future__ import annotations

import base64
import json
import time

import pytest

from app.codex.auth_state import AuthStateError, CodexAuthStore, decode_jwt_payload


def _jwt(payload):
    def enc(obj):
        raw = json.dumps(obj, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{enc({'alg': 'none'})}.{enc(payload)}.sig"


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
