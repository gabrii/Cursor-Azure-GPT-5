"""Codex upstream HTTP helpers."""

from __future__ import annotations

from typing import Any

import requests

from .auth_state import CodexAuthState
from .settings import CodexSettings


def build_upstream_headers(
    settings: CodexSettings,
    auth: CodexAuthState,
    *,
    session_id: str | None,
    thread_id: str | None,
    downstream_headers: dict[str, str],
) -> dict[str, str]:
    """Build headers for ChatGPT Codex backend requests."""
    headers = {
        "Authorization": f"Bearer {auth.access_token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "originator": settings.originator,
        "User-Agent": settings.user_agent,
    }
    if auth.account_id:
        headers["ChatGPT-Account-Id"] = auth.account_id
    if auth.fedramp:
        headers["X-OpenAI-Fedramp"] = "true"
    if session_id:
        headers["session_id"] = session_id
        headers["session-id"] = session_id
    if thread_id:
        headers["thread_id"] = thread_id
        headers["thread-id"] = thread_id
        headers["x-client-request-id"] = thread_id
    incoming_request_id = _header_get(downstream_headers, "x-request-id")
    if incoming_request_id and "x-client-request-id" not in headers:
        headers["x-client-request-id"] = incoming_request_id
    return headers


def post_responses(
    url: str,
    headers: dict[str, str],
    json_body: dict[str, Any],
    *,
    timeout: float,
) -> requests.Response:
    """Post one Codex Responses request."""
    return requests.post(
        url,
        headers=headers,
        json=json_body,
        stream=True,
        timeout=(60.0, timeout),
    )


def _header_get(headers: dict[str, str], key: str) -> str | None:
    for actual, value in headers.items():
        if actual.lower() == key.lower() and value:
            return value
    return None
