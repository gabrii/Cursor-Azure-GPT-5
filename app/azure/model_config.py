"""Model and deployment configuration helpers."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from ..exceptions import CursorConfigurationError, ServiceConfigurationError

REASONING_MODEL_EFFORTS = {
    "gpt-high": "high",
    "gpt-medium": "medium",
    "gpt-low": "low",
    "gpt-minimal": "minimal",
}
VALID_REASONING_EFFORTS = set(REASONING_MODEL_EFFORTS.values())


def parse_deployment_map(value: Any) -> Dict[str, str]:
    """Return a validated model->deployment mapping from config."""
    if value in (None, "", {}):
        return {}

    if isinstance(value, dict):
        mapping = value
    elif isinstance(value, str):
        try:
            mapping = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ServiceConfigurationError(
                "AZURE_DEPLOYMENT_MAP must be valid JSON."
            ) from exc
    else:
        raise ServiceConfigurationError(
            "AZURE_DEPLOYMENT_MAP must be a JSON object mapping model names "
            "to deployment names."
        )

    if not isinstance(mapping, dict):
        raise ServiceConfigurationError(
            "AZURE_DEPLOYMENT_MAP must be a JSON object mapping model names "
            "to deployment names."
        )

    cleaned: Dict[str, str] = {}
    for model, deployment in mapping.items():
        if not isinstance(model, str) or not model:
            raise ServiceConfigurationError(
                "AZURE_DEPLOYMENT_MAP keys must be non-empty strings."
            )
        if not isinstance(deployment, str) or not deployment:
            raise ServiceConfigurationError(
                "AZURE_DEPLOYMENT_MAP values must be non-empty strings."
            )
        cleaned[model] = deployment
    return cleaned


def resolve_model_settings(inbound_model: Any, settings: Dict[str, Any]) -> Tuple[str, str]:
    """Return (deployment, reasoning_effort) for the inbound model."""
    if not isinstance(inbound_model, str) or not inbound_model:
        raise CursorConfigurationError("Model name must be a non-empty string.")

    deployment_map = parse_deployment_map(settings.get("AZURE_DEPLOYMENT_MAP", ""))

    if inbound_model in REASONING_MODEL_EFFORTS:
        deployment = deployment_map.get(inbound_model, settings["AZURE_DEPLOYMENT"])
        return deployment, REASONING_MODEL_EFFORTS[inbound_model]

    if inbound_model in deployment_map:
        effort = settings.get("AZURE_REASONING_EFFORT", "medium")
        if effort not in VALID_REASONING_EFFORTS:
            raise ServiceConfigurationError(
                "AZURE_REASONING_EFFORT must be either minimal, low, medium, or high."
                f"\n\nGot: {effort}"
            )
        return deployment_map[inbound_model], effort

    allowed = list(REASONING_MODEL_EFFORTS.keys()) + [
        model for model in deployment_map.keys() if model not in REASONING_MODEL_EFFORTS
    ]
    if deployment_map:
        allowed_list = ", ".join(allowed)
        raise CursorConfigurationError(
            "Model name must be one of: "
            f"{allowed_list}."
            f"\n\nGot: {inbound_model}"
        )

    raise CursorConfigurationError(
        "Model name must be either gpt-high, gpt-medium, gpt-low, or gpt-minimal."
        f"\n\nGot: {inbound_model}"
    )


def available_models(settings: Dict[str, Any]) -> List[str]:
    """Return a list of models available to the client."""
    deployment_map = parse_deployment_map(settings.get("AZURE_DEPLOYMENT_MAP", ""))
    models = list(REASONING_MODEL_EFFORTS.keys())
    for model in deployment_map.keys():
        if model not in models:
            models.append(model)
    return models
