"""Unit tests for Azure request adaptation."""

import pytest

from app.azure.adapter import AzureAdapter
from app.exceptions import CursorConfigurationError


def test_request_adapter_prefers_inbound_reasoning_effort(app):
    """Use the inbound reasoning effort for bare Cursor model names."""
    adapter = AzureAdapter().request_adapter
    request = app.test_request_context(
        "/chat/completions",
        method="POST",
        json={
            "model": "gpt-5.4",
            "input": [
                {"role": "user", "content": [{"type": "input_text", "text": "Hi"}]}
            ],
            "reasoning": {"effort": "high", "summary": "auto"},
            "stream": True,
            "user": "cursor-user",
        },
        headers={"Authorization": "Bearer test-service-api-key"},
    ).request

    request_kwargs = adapter.adapt(request)

    assert request_kwargs["json"]["model"] == "gpt-5.4"
    assert request_kwargs["json"]["reasoning"]["effort"] == "high"
    assert request_kwargs["json"]["reasoning"]["summary"] == "auto"


def test_request_adapter_requires_reasoning_for_bare_model(app):
    """Reject bare model names when Cursor omits native reasoning settings."""
    adapter = AzureAdapter().request_adapter
    request = app.test_request_context(
        "/chat/completions",
        method="POST",
        json={
            "model": "gpt-5.4",
            "input": [
                {"role": "user", "content": [{"type": "input_text", "text": "Hi"}]}
            ],
            "stream": True,
            "user": "cursor-user",
        },
        headers={"Authorization": "Bearer test-service-api-key"},
    ).request

    with pytest.raises(CursorConfigurationError) as exc_info:
        adapter.adapt(request)

    assert "Cursor must send reasoning.effort" in str(exc_info.value)
