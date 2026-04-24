"""Shared model support metadata for the proxy."""

from __future__ import annotations

import json
from typing import Final

from .exceptions import ServiceConfigurationError

SUPPORTED_MODELS: Final[tuple[str, ...]] = (
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-codex",
    "gpt-5.1",
    "gpt-5.1-codex",
    "gpt-5.1-codex-max",
    "gpt-5.1-codex-mini",
    "gpt-5.2",
    "gpt-5.2-codex",
    "gpt-5.3-codex",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
)

SUPPORTED_MODELS_TEXT: Final[str] = "\n".join(
    f"  {model}" for model in SUPPORTED_MODELS
)


def default_model_deployments() -> dict[str, str]:
    """Return the default public-model to Azure-deployment mapping."""
    return {model: model for model in SUPPORTED_MODELS}


def parse_model_deployments(raw_mapping: str | None) -> dict[str, str]:
    """Parse a JSON mapping of public model ids to Azure deployment names."""
    deployments = default_model_deployments()
    if not raw_mapping:
        return deployments

    try:
        parsed = json.loads(raw_mapping)
    except json.JSONDecodeError as exc:
        raise ServiceConfigurationError(
            "AZURE_MODEL_DEPLOYMENTS must be valid JSON mapping model ids to deployment names."
        ) from exc

    if not isinstance(parsed, dict):
        raise ServiceConfigurationError(
            "AZURE_MODEL_DEPLOYMENTS must be a JSON object mapping model ids to deployment names."
        )

    unknown_models = sorted(set(parsed) - set(SUPPORTED_MODELS))
    if unknown_models:
        raise ServiceConfigurationError(
            "AZURE_MODEL_DEPLOYMENTS contains unsupported model ids:\n"
            + "\n".join(f"  {model}" for model in unknown_models)
        )

    for model, deployment in parsed.items():
        if not isinstance(deployment, str) or not deployment.strip():
            raise ServiceConfigurationError(
                f"AZURE_MODEL_DEPLOYMENTS[{model!r}] must be a non-empty string."
            )
        deployments[model] = deployment.strip()

    return deployments
