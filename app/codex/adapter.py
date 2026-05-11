"""Flask adapter for the Codex provider."""

from __future__ import annotations

from typing import Any

import requests
from flask import Request, Response, jsonify

from .auth_state import AuthStateError, CodexAuthManager, CodexAuthStore
from .request_adapter import CursorRequestAdapter, UnsupportedCursorShape
from .response_adapter import adapt_responses_sse_to_chat_sse
from .settings import CodexSettings
from .upstream import build_upstream_headers, post_responses


class CodexAdapter:
    """Forward Flask requests to the ChatGPT Codex backend."""

    def __init__(self, settings: CodexSettings | None = None) -> None:
        """Initialize the adapter with current Flask-backed settings."""
        self.settings = settings or CodexSettings()

    def ready(self) -> Response:
        """Return Codex readiness based on local auth state."""
        try:
            CodexAuthStore(self.settings.codex_auth_path).validate_ready()
        except AuthStateError as exc:
            return jsonify({"status": "not_ready", "error": str(exc)}), 503
        return jsonify({"status": "ready"})

    def forward(self, req: Request, provider_path: str) -> Response:
        """Forward a request to Codex and adapt the response when needed."""
        payload = req.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": {"message": "Request body must be JSON"}}), 400

        downstream_headers = dict(req.headers)
        try:
            adapted = CursorRequestAdapter(self.settings).adapt(
                provider_path, payload, downstream_headers
            )
            auth = CodexAuthManager(
                CodexAuthStore(self.settings.codex_auth_path),
                refresh_skew_seconds=self.settings.token_refresh_skew_seconds,
            ).current()
        except (UnsupportedCursorShape, AuthStateError) as exc:
            return jsonify({"error": {"message": str(exc)}}), 400

        headers = build_upstream_headers(
            self.settings,
            auth,
            session_id=adapted.session_id,
            thread_id=adapted.thread_id,
            downstream_headers=downstream_headers,
        )
        try:
            upstream_response = post_responses(
                self.settings.codex_responses_url,
                headers,
                adapted.body,
                timeout=self.settings.request_timeout_seconds,
            )
        except requests.RequestException as exc:
            return (
                jsonify(
                    {"error": {"message": f"Codex upstream request failed: {exc}"}}
                ),
                502,
            )

        content = _response_content(upstream_response)
        if (
            _wants_chat_completion_response(provider_path)
            and upstream_response.status_code == 200
        ):
            content = b"".join(
                adapt_responses_sse_to_chat_sse(
                    [content], model=str(adapted.body.get("model", ""))
                )
            )

        return Response(
            content,
            status=upstream_response.status_code,
            headers={
                "content-type": upstream_response.headers.get(
                    "content-type", "text/event-stream"
                ),
                "cache-control": "no-cache",
            },
        )


def _wants_chat_completion_response(path: str) -> bool:
    return path.rstrip("/").endswith("/chat/completions")


def _response_content(response: Any) -> bytes:
    content = getattr(response, "content", None)
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode()
    return b"".join(response.iter_content(chunk_size=8192))
