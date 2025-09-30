"""Lightweight recording helpers for debugging request/response flows.

Artifacts are stored under the project-level ``recordings/`` folder. Each
request/response lifecycle is grouped in a subdirectory named by an increasing
numeric index, e.g.
``recordings/9/downstream_request.json``.
"""

import json
import os
import re
from functools import wraps
from typing import Any, Dict

from flask import current_app

RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "recordings")

# Private, module-level counter tracking the latest recording index.
__LAST_RECORDING_INDEX = -1


def config_bypass(func):
    """Bypass the wrapped function when RECORD_TRAFFIC is disabled."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        enabled = current_app.config["RECORD_TRAFFIC"]
        if not enabled:
            return None
        return func(*args, **kwargs)

    return wrapper


@config_bypass
def init_last_recording() -> None:
    """Initialize the recording index counter.

    Scans existing subdirectories in the recordings directory so that subsequent
    runs continue incrementing from the maximum observed index.
    """
    global __LAST_RECORDING_INDEX
    if __LAST_RECORDING_INDEX != -1:
        return
    try:
        entries = os.listdir(RECORDINGS_DIR)
    except FileNotFoundError:
        # Create the recordings directory lazily when first used
        os.makedirs(RECORDINGS_DIR, exist_ok=True)
        entries = []

    for entry in entries:
        try:
            recording_index = int(entry)
            if recording_index > __LAST_RECORDING_INDEX:
                __LAST_RECORDING_INDEX = recording_index
        except ValueError:
            # Ignore unrelated folders that do not use a numeric name
            pass
    if __LAST_RECORDING_INDEX == -1:
        __LAST_RECORDING_INDEX = 0


@config_bypass
def increment_last_recording() -> None:
    """Advance the shared recording index for a new request lifecycle."""

    global __LAST_RECORDING_INDEX
    __LAST_RECORDING_INDEX += 1


def anonimize(data: str) -> str:
    """Removes sensitive data from recordings."""
    closing = r'(.*?[^\\](?:\\\\)?)(")'
    patterns = (
        # Content
        r'("role": ?"[a-z]+",\s+"content": ?")',  # Completions
        r'("instructions": ?")',  # Responses
        r'("text": ?")',  # Responses
        r'("role": ?"[a-z]+",\s+"delta": ?")',  # Both
        # User identifiers
        r'("user": ?")',  # Completions
        r'("prompt_cache_key": ?")',  # Responses
        # Function calls
        r'("name": ?")',  # Both
        r'("description": ?")',  # Both
    )
    for pattern in patterns:
        data = re.sub(pattern + closing, r"\1REDACTED\3", data)

    return data


def _recording_file_path(name: str, ext: str) -> str:
    dir_path = os.path.join(RECORDINGS_DIR, str(__LAST_RECORDING_INDEX))
    os.makedirs(dir_path, exist_ok=True)
    return os.path.join(dir_path, f"{name}.{ext}")


@config_bypass
def record_payload(payload: Dict[str, Any], name: str) -> None:
    """Write a JSON payload under the current recording index subdirectory."""

    file_path = _recording_file_path(name, "json")
    with open(file_path, "w") as f:
        data = json.dumps(payload, indent=2)
        data = anonimize(data)
        f.write(data)


@config_bypass
def record_sse(sse: bytes, name: str) -> None:
    """Write raw SSE bytes under the current recording index subdirectory."""

    file_path = _recording_file_path(name, "sse")
    with open(file_path, "wb") as f:
        sse = anonimize(sse.decode("utf-8")).encode("utf-8")
        f.write(sse)
