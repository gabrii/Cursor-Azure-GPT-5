"""Flask blueprint and request routing for the proxy service.

This module defines the application blueprint, configures logging, and
forwards incoming HTTP requests to the configured backend implementation.
"""

import os
import sys

from flask import Blueprint, jsonify, request
from loguru import logger
from rich.traceback import install as install_rich_traceback

from .azure.adapter import AzureAdapter
from .backend_openai import OpenAIBackend
from .common.logging import log_request

blueprint = Blueprint("blueprint", __name__)

# Pretty tracebacks for easier debugging
install_rich_traceback(show_locals=False)

# Choose backend CLASS based on env: AZURE or OPENAI
adapter_choice = os.environ.get("BACKEND", "AZURE").strip().upper()
if adapter_choice == "OPENAI":
    adapter_class = OpenAIBackend
    logger.info("Using backend: OPENAI")
else:
    adapter_class = AzureAdapter
    logger.info("Using backend: AZURE")


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
def catch_all(path: str):
    """Forward any request path to the configured backend.

    Logs the incoming request and forwards it to the selected backend
    implementation, returning the backend's response. If forwarding fails,
    returns a 502 JSON error payload.
    """
    # Log the request details
    log_request(request)
    # Forward the request to selected backend and return its response
    backend = adapter_class()
    return backend.forward(request)
