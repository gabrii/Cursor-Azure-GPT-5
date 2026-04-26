"""Unit tests for Azure request adaptation."""

import pytest

from app.azure.adapter import AzureAdapter
from app.exceptions import CursorConfigurationError
from app.models import SUPPORTED_MODELS


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


@pytest.mark.parametrize("model_name", SUPPORTED_MODELS)
def test_request_adapter_accepts_supported_bare_models(app, model_name):
    """Accept every supported bare model and forward Cursor reasoning."""
    adapter = AzureAdapter().request_adapter
    request = app.test_request_context(
        "/chat/completions",
        method="POST",
        json={
            "model": model_name,
            "input": [
                {"role": "user", "content": [{"type": "input_text", "text": "Hi"}]}
            ],
            "reasoning": {"effort": "medium", "summary": "auto"},
            "stream": True,
            "user": "cursor-user",
        },
        headers={"Authorization": "Bearer test-service-api-key"},
    ).request

    request_kwargs = adapter.adapt(request)

    assert request_kwargs["json"]["model"] == model_name
    assert request_kwargs["json"]["reasoning"]["effort"] == "medium"


def test_request_adapter_uses_configured_deployment_mapping(app):
    """Map public model ids to custom Azure deployment names."""
    app.config["AZURE_MODEL_DEPLOYMENTS"]["gpt-5.4"] = "my-custom-54-deployment"
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

    assert request_kwargs["json"]["model"] == "my-custom-54-deployment"
    assert adapter.adapter.inbound_model == "gpt-5.4"


def test_request_adapter_routes_gpt_55_to_configured_deployment(app):
    """Route gpt-5.5 through the configured Azure deployment name."""
    app.config["AZURE_MODEL_DEPLOYMENTS"]["gpt-5.5"] = "gpt-5.5-1"
    adapter = AzureAdapter().request_adapter
    request = app.test_request_context(
        "/chat/completions",
        method="POST",
        json={
            "model": "gpt-5.5",
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

    assert request_kwargs["json"]["model"] == "gpt-5.5-1"
    assert adapter.adapter.inbound_model == "gpt-5.5"


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


def test_request_adapter_strips_include_usage_for_azure(app):
    """Strip include_usage from stream_options (unsupported by Azure Responses API)."""
    azure_adapter = AzureAdapter()
    adapter = azure_adapter.request_adapter
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
            "stream_options": {"include_usage": True, "include_obfuscation": True},
            "user": "cursor-user",
        },
        headers={"Authorization": "Bearer test-service-api-key"},
    ).request

    request_kwargs = adapter.adapt(request)

    # include_usage must NOT be forwarded to Azure Responses API
    assert "include_usage" not in request_kwargs["json"]["stream_options"]
    # include_obfuscation is always forced to False
    assert request_kwargs["json"]["stream_options"]["include_obfuscation"] is False
    # The flag should be stored on the shared adapter for the response side
    assert azure_adapter.include_usage is True
