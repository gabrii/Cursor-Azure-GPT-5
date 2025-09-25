"""Flask blueprint and request routing for the proxy service.

This module defines the application blueprint, configures logging, and
forwards incoming HTTP requests to the configured backend implementation.
"""

import sys

from flask import Blueprint, jsonify, request
from loguru import logger
from rich.traceback import install as install_rich_traceback

from .auth import require_auth
from .azure.adapter import AzureAdapter
from .common.logging import log_request
from .common.recording import (
    increment_last_recording,
    init_last_recording,
    record_payload,
)
from .exceptions import ConfigurationError

blueprint = Blueprint("blueprint", __name__)

# Pretty tracebacks for easier debugging
install_rich_traceback(show_locals=False)


# Configure Loguru to print colorful logs to stdout
logger.remove()
logger.add(
    sys.stdout,
    colorize=True,
    enqueue=False,
    backtrace=False,
    diagnose=False,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> "
        "| <level>{level: <8}</level> "
        "| <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> "
        "- <level>{message}</level>"
    ),
)


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


@blueprint.route("/health", methods=["GET"])
def health():
    """Return a simple health check payload."""
    return jsonify({"status": "ok"})


@blueprint.route("/", defaults={"path": ""}, methods=ALL_METHODS)
@blueprint.route("/<path:path>", methods=ALL_METHODS)
@require_auth
def catch_all(path: str):
    """Forward any request path to the Azure backend.

    Logs the incoming request and forwards it to the selected backend
    implementation, returning the backend's response. If forwarding fails,
    returns a 502 JSON error payload.
    """
    log_request(request)
    init_last_recording()
    increment_last_recording()
    record_payload(request.json, "downstream_request")
    adapter = AzureAdapter()
    return adapter.forward(request)


@blueprint.route("/models", methods=["GET"])
@blueprint.route("/v1/models", methods=["GET"])
@require_auth
def models():
    """Return a list of available models."""
    models = [
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
