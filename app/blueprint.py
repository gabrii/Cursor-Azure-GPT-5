"""Flask blueprint and request routing for the proxy service.

This module defines the application blueprint, configures logging, and
forwards incoming HTTP requests to the configured backend implementation.
"""

import os

from flask import Blueprint, Response, current_app, jsonify, request

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

VALID_EFFORTS = {"none", "low", "medium", "high", "xhigh"}

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


# ── Control panel (no auth — it's a simple UI, not an API) ──────────────────


@blueprint.route("/panel", methods=["GET"])
def panel():
    """Serve the reasoning effort control panel."""
    html_path = os.path.join(os.path.dirname(__file__), "static", "panel.html")
    with open(html_path) as f:
        return Response(f.read(), content_type="text/html")


@blueprint.route("/settings", methods=["GET"])
def get_settings():
    """Return current effort settings as JSON."""
    return jsonify(current_app.config["EFFORT_SETTINGS"])


@blueprint.route("/settings", methods=["POST"])
def set_settings():
    """Update reasoning effort for a model."""
    data = request.get_json(silent=True) or {}
    model = data.get("model")
    effort = data.get("effort")

    if model not in current_app.config["EFFORT_SETTINGS"]:
        return jsonify({"error": f"Unknown model: {model}"}), 400
    if effort not in VALID_EFFORTS:
        return jsonify({"error": f"Invalid effort: {effort}"}), 400

    current_app.config["EFFORT_SETTINGS"][model] = effort
    console.print(f"[bold green]Effort updated:[/bold green] {model} → {effort}")
    return jsonify(current_app.config["EFFORT_SETTINGS"])


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
    except Exception:
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
        # gpt-5.4 — full model, ordered by reasoning effort ascending
        "gpt-5.4-none",
        "gpt-5.4-low",
        "gpt-5.4-medium",
        "gpt-5.4-high",
        "gpt-5.4-xhigh",
        # gpt-5.4-mini — faster/cheaper, same effort levels
        "gpt-5.4-mini-none",
        "gpt-5.4-mini-low",
        "gpt-5.4-mini-medium",
        "gpt-5.4-mini-high",
        "gpt-5.4-mini-xhigh",
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
