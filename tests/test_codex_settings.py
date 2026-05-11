"""Unit tests for Codex settings parsing."""

import pytest

from app.codex.settings import (
    parse_codex_model_rewrites,
    parse_codex_supported_models,
)
from app.exceptions import ServiceConfigurationError


def test_codex_supported_models_can_be_overridden():
    """Codex model list is comma-separated and ordered."""
    assert parse_codex_supported_models("gpt-5.5,gpt-5.4-mini") == (
        "gpt-5.5",
        "gpt-5.4-mini",
    )


def test_codex_model_rewrites_can_be_configured():
    """Codex model rewrites use source:target entries."""
    rewrites = parse_codex_model_rewrites(
        "gpt-5.4:gpt-5.5", supported_models=("gpt-5.5", "gpt-5.4")
    )

    assert rewrites == {"gpt-5.4": "gpt-5.5"}


def test_codex_model_rewrites_reject_unknown_models():
    """Model rewrite entries must reference Codex-supported models."""
    with pytest.raises(ServiceConfigurationError, match="unsupported model"):
        parse_codex_model_rewrites(
            "gpt-5.4:gpt-unknown", supported_models=("gpt-5.5", "gpt-5.4")
        )
