"""Flask blueprint and request routing for the proxy service.

This module defines the application blueprint, configures logging, and
forwards incoming HTTP requests to the configured backend implementation.
"""

from flask import Blueprint, current_app, jsonify, request

from .auth import require_auth
from .azure.adapter import AzureAdapter
from .common.logging import console, log_request
from .common.recording import (
    increment_last_recording,
    init_last_recording,
    record_payload,
)
from .exceptions import ConfigurationError

blueprint = Blueprint("blueprint", __name__)

ALL_METHODS = [
    "GET",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
    "HEAD",
    "TRACE",
]


# ── Health check ────────────────────────────────────────────────────────────


@blueprint.route("/health", methods=["GET"])
def health():
    """Return a simple health check payload."""
    return jsonify({"status": "ok"})


# ── Proxy catch-all ─────────────────────────────────────────────────────────


@blueprint.route("/", defaults={"path": ""}, methods=ALL_METHODS)
@blueprint.route("/<path:path>", methods=ALL_METHODS)
@require_auth
def catch_all(path: str):
    """Forward any request path to the Azure backend.

    Logs the incoming request and forwards it to the selected backend
    implementation, returning the backend's response. If forwarding fails,
    returns a 502 JSON error payload.
    """
    # Logging / recording must never crash the actual request
    try:
        if current_app.config.get("LOG_CONTEXT"):
            log_request(request)
        init_last_recording()
        increment_last_recording()
        record_payload(request.get_json(silent=True), "downstream_request")
    except (TypeError, ValueError):
        console.print_exception()
        console.print("[yellow]Logging failed but continuing with request[/yellow]")

    adapter = AzureAdapter()
    return adapter.forward(request)


# ── Model list ──────────────────────────────────────────────────────────────


@blueprint.route("/models", methods=["GET"])
@blueprint.route("/v1/models", methods=["GET"])
@require_auth
def models():
    """Return a list of available models."""
    models = [
        # Native Cursor reasoning controls set effort in the request payload.
        "gpt-5.4",
        "gpt-5.4-mini",
        # Legacy custom models kept for backwards compatibility.
        "gpt-high",
        "gpt-medium",
        "gpt-low",
        "gpt-minimal",
    ]
    return jsonify(
        {
            "object": "list",
            "data": [
                {
                    "id": model,
                    "object": "model",
                    "created": 1686935002,
                    "owned_by": "openai",
                }
                for model in models
            ],
        }
    )


@blueprint.errorhandler(ConfigurationError)
def configuration_error(e: ConfigurationError):
    """Return a 400 JSON error payload for ValueError."""
    return e.get_response_content(), 400
