"""Unit tests for Codex request adaptation."""

from __future__ import annotations

import pytest

from app.codex.request_adapter import CursorRequestAdapter, UnsupportedCursorShape


class Settings:
    """Minimal settings object for adapter unit tests."""

    def __init__(
        self,
        *,
        discovery_mode=False,
        supported_models=("gpt-5.5", "gpt-5.4", "gpt-5.4-mini"),
        model_rewrites=None,
    ):
        """Initialize test settings."""
        self.discovery_mode = discovery_mode
        self.supported_models = supported_models
        self.model_rewrites = model_rewrites or {}


def test_codex_responses_payload_is_preserved():
    """Responses payloads are mostly passed through with Cursor-only fields stripped."""
    adapter = CursorRequestAdapter(Settings(discovery_mode=True))
    payload = {
        "model": "gpt-5.5",
        "instructions": "be direct",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "hi"}]}],
        "reasoning": {"effort": "high"},
        "tools": [{"type": "function", "name": "Shell", "parameters": {}}],
        "stream": True,
        "metadata": {"cursorConversationId": "conv-1"},
    }

    adapted = adapter.adapt("/v1/responses", payload, headers={})

    assert adapted.body["model"] == "gpt-5.5"
    assert adapted.body["instructions"] == "be direct"
    assert adapted.body["input"] == payload["input"]
    assert adapted.body["tools"] == payload["tools"]
    assert adapted.body["reasoning"] == {"effort": "high"}
    assert adapted.body["store"] is False
    assert "metadata" not in adapted.body
    assert "user" not in adapted.body
    assert adapted.session_id == "conv-1"
    assert adapted.thread_id == "conv-1"


def test_codex_responses_payload_defaults_missing_instructions():
    """Responses payloads get default instructions and normalized string input."""
    adapter = CursorRequestAdapter(Settings(discovery_mode=True))

    adapted = adapter.adapt(
        "/v1/responses",
        {"model": "gpt-5.5", "input": "hello", "reasoning": {"effort": "low"}},
        headers={},
    )

    assert adapted.body["instructions"]
    assert adapted.body["store"] is False
    assert adapted.body["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "hello"}]}
    ]


def test_codex_chat_completions_url_with_responses_input_uses_body_shape():
    """Cursor may call chat completions with a Responses-shaped body."""
    adapter = CursorRequestAdapter(Settings(discovery_mode=True))

    adapted = adapter.adapt(
        "/chat/completions",
        {
            "model": "gpt-5.4",
            "input": [
                {"role": "system", "content": "system text"},
                {"role": "user", "content": "plain text"},
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "structured text"}],
                },
            ],
            "tools": [{"type": "function", "name": "Shell", "parameters": {}}],
            "include": ["reasoning.encrypted_content"],
            "reasoning": {"effort": "medium", "summary": "auto"},
            "metadata": {"cursorConversationId": "conv-1"},
            "user": "cursor-user-hash",
            "prompt_cache_retention": "24h",
        },
        headers={"user-agent": "Cursor/1.0"},
    )

    assert adapted.body["instructions"] == "system text"
    assert adapted.body["input"] == [
        {"role": "user", "content": [{"type": "input_text", "text": "plain text"}]},
        {
            "role": "user",
            "content": [{"type": "input_text", "text": "structured text"}],
        },
    ]
    assert adapted.body["tools"] == [
        {"type": "function", "name": "Shell", "parameters": {}}
    ]
    assert adapted.body["include"] == ["reasoning.encrypted_content"]
    assert adapted.body["reasoning"] == {"effort": "medium", "summary": "auto"}
    assert adapted.body["store"] is False
    assert "metadata" not in adapted.body
    assert "user" not in adapted.body
    assert "prompt_cache_retention" not in adapted.body
    assert adapted.session_id == "conv-1"


def test_codex_chat_completions_payload_converts_to_responses():
    """Chat Completions messages are converted to Responses input items."""
    adapter = CursorRequestAdapter(Settings(discovery_mode=True))
    payload = {
        "model": "gpt-5.4-mini",
        "messages": [
            {"role": "system", "content": "system text"},
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "Shell", "arguments": '{"cmd":"ls"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        ],
        "tools": [
            {
                "type": "function",
                "function": {"name": "Shell", "description": "run", "parameters": {}},
            }
        ],
        "tool_choice": {"type": "function", "function": {"name": "Shell"}},
        "reasoning": {"effort": "low"},
        "stream": True,
        "user": "cursor-user-hash",
    }

    adapted = adapter.adapt("/v1/chat/completions", payload, headers={})

    assert adapted.body["model"] == "gpt-5.4-mini"
    assert adapted.body["instructions"] == "system text"
    assert adapted.body["input"][0]["role"] == "user"
    assert adapted.body["input"][1]["type"] == "function_call"
    assert adapted.body["input"][2]["type"] == "function_call_output"
    assert adapted.body["tools"] == [
        {
            "type": "function",
            "name": "Shell",
            "description": "run",
            "parameters": {},
            "strict": False,
        }
    ]
    assert adapted.body["tool_choice"] == {"type": "function", "name": "Shell"}
    assert adapted.body["store"] is False
    assert adapted.session_id == "cursor-user-hash"


def test_codex_model_rewrite_changes_upstream_model_only_after_validation():
    """Model rewrite happens after supported-model validation."""
    adapter = CursorRequestAdapter(
        Settings(
            discovery_mode=True,
            supported_models=("gpt-5.5", "gpt-5.4"),
            model_rewrites={"gpt-5.4": "gpt-5.5"},
        )
    )

    adapted = adapter.adapt(
        "/chat/completions",
        {
            "model": "gpt-5.4",
            "input": [{"role": "user", "content": "hello"}],
            "reasoning": {"effort": "medium", "summary": "auto"},
        },
        headers={"user-agent": "Cursor/1.0"},
    )

    assert adapted.body["model"] == "gpt-5.5"
    assert adapted.body["reasoning"] == {"effort": "medium", "summary": "auto"}


def test_codex_normal_mode_requires_cursor_marker():
    """Normal mode rejects requests without Cursor markers."""
    adapter = CursorRequestAdapter(Settings(discovery_mode=False))

    with pytest.raises(UnsupportedCursorShape, match="Cursor Request Marker"):
        adapter.adapt(
            "/v1/responses",
            {"model": "gpt-5.5", "input": "hi", "reasoning": {"effort": "low"}},
            headers={},
        )


def test_codex_unknown_model_is_rejected():
    """Unknown models are rejected before forwarding."""
    adapter = CursorRequestAdapter(Settings(discovery_mode=True))

    with pytest.raises(UnsupportedCursorShape, match="Unsupported model"):
        adapter.adapt(
            "/v1/responses",
            {"model": "gpt-unknown", "input": "hi", "reasoning": {"effort": "low"}},
            headers={},
        )
