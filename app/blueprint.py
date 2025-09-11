import os
import sys
from typing import List

from flask import Blueprint, Flask, jsonify, request
from loguru import logger
from rich.traceback import install as install_rich_traceback

from .azure.adapter import AzureAdapter
from .backend_azure import AzureBackend
from .backend_openai import OpenAIBackend
from .common.logging import log_request, should_redact

blueprint = Blueprint("blueprint", __name__)

# Pretty tracebacks for easier debugging
install_rich_traceback(show_locals=False)

# Choose backend CLASS based on env: OPENAI (default) or AZURE or NEW_AZURE
backend_choice = os.environ.get("BACKEND", "OPENAI").strip().upper()
if backend_choice == "AZURE":
    backend_class = AzureBackend
    logger.info("Using backend: AZURE")
elif backend_choice == "NEW_AZURE":
    if AzureAdapter is None:
        logger.warning(
            "NEW_AZURE requested but azure package not importable; falling back to AZURE"
        )
        backend_class = AzureBackend
        logger.info("Using backend: AZURE (fallback)")
    else:
        backend_class = AzureAdapter
        logger.info("Using backend: NEW_AZURE")
else:
    backend_class = OpenAIBackend
    logger.info("Using backend: OPENAI")


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
    return jsonify({"status": "ok"})

@blueprint.route("/", defaults={"path": ""}, methods=ALL_METHODS)
@blueprint.route("/<path:path>", methods=ALL_METHODS)
def catch_all(path: str):
    # Log the request details
    log_request(request)
    # Forward the request to selected backend and return its response
    try:
        backend = backend_class()
        return backend.forward(request)
    except Exception as exc:
        logger.exception("Backend forwarding failed: {}", exc)
        return (
            jsonify({"error": "backend_forward_failed", "message": str(exc)}),
            502,
            {"Content-Type": "application/json"},
        )

# def main():
#     host = os.environ.get("HOST", "0.0.0.0")
#     port = int(os.environ.get("PORT", "8000"))
#     debug_env = os.environ.get("DEBUG", "true").strip().lower() in {"1", "true", "yes", "on"}
#     logger.info(
#         "Starting server on {}:{} (debug={}) — LOG_REDACT={}",
#         host,
#         port,
#         debug_env,
#         should_redact(),
#     )
#     app.run(host=host, port=port, debug=debug_env, use_reloader=False)


# if __name__ == "__main__":
#     main()
