"""Codex provider settings helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import current_app

from ..exceptions import ServiceConfigurationError

DEFAULT_CODEX_MODELS = (
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
)


def parse_codex_supported_models(raw: str | None) -> tuple[str, ...]:
    """Parse a comma-separated Codex model list."""
    if not raw:
        return DEFAULT_CODEX_MODELS
    models = tuple(item.strip() for item in raw.split(",") if item.strip())
    return models or DEFAULT_CODEX_MODELS


def parse_codex_model_rewrites(
    raw: str | None, *, supported_models: tuple[str, ...]
) -> dict[str, str]:
    """Parse CODEX_MODEL_REWRITES source:target entries."""
    if not raw:
        return {}

    rewrites: dict[str, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise ServiceConfigurationError(
                "CODEX_MODEL_REWRITES entries must use source:target format."
            )
        source, target = (part.strip() for part in item.split(":", 1))
        if not source or not target:
            raise ServiceConfigurationError(
                "CODEX_MODEL_REWRITES entries must include both source and target models."
            )
        rewrites[source] = target

    supported = set(supported_models)
    unsupported = sorted(
        model for pair in rewrites.items() for model in pair if model not in supported
    )
    if unsupported:
        raise ServiceConfigurationError(
            "CODEX_MODEL_REWRITES references unsupported model(s): "
            + ", ".join(unsupported)
        )
    return rewrites


class CodexSettings:
    """Current Flask config projected into Codex provider settings."""

    @property
    def codex_auth_path(self) -> Path:
        """Return the local Codex auth-state path."""
        return Path(current_app.config["CODEX_AUTH_PATH"]).expanduser()

    @property
    def supported_models(self) -> tuple[str, ...]:
        """Return provider-local Codex model IDs."""
        return tuple(current_app.config["CODEX_SUPPORTED_MODELS"])

    @property
    def model_rewrites(self) -> dict[str, str]:
        """Return configured Codex source-to-target model rewrites."""
        return dict(current_app.config.get("CODEX_MODEL_REWRITES") or {})

    @property
    def discovery_mode(self) -> bool:
        """Return whether Cursor marker validation is relaxed."""
        return bool(current_app.config["CODEX_DISCOVERY_MODE"])

    @property
    def codex_responses_url(self) -> str:
        """Return the Codex Responses upstream URL."""
        return str(current_app.config["CODEX_RESPONSES_URL"])

    @property
    def originator(self) -> str:
        """Return the Codex originator header value."""
        return str(current_app.config["CODEX_ORIGINATOR"])

    @property
    def user_agent(self) -> str:
        """Return the Codex upstream user-agent value."""
        return str(current_app.config["CODEX_USER_AGENT"])

    @property
    def token_refresh_skew_seconds(self) -> int:
        """Return token refresh skew in seconds."""
        return int(current_app.config["CODEX_TOKEN_REFRESH_SKEW_SECONDS"])

    @property
    def request_timeout_seconds(self) -> float:
        """Return Codex upstream request timeout in seconds."""
        return float(current_app.config["CODEX_REQUEST_TIMEOUT_SECONDS"])


def codex_model_payload(settings: Any | None = None) -> dict[str, Any]:
    """Return OpenAI-compatible model list payload for Codex."""
    settings = settings or CodexSettings()
    return {
        "object": "list",
        "data": [
            {
                "id": model,
                "object": "model",
                "created": 1686935002,
                "owned_by": "openai",
            }
            for model in settings.supported_models
        ],
    }
