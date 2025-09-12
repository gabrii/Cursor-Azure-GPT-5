"""Response adaptation helpers for Azure Responses API streams.

This module defines ResponseAdapter, which converts Azure SSE streams into
OpenAI Chat Completions-compatible streaming responses.
"""

from __future__ import annotations

import random
import time
from string import ascii_letters, digits
from typing import Any, Dict, Iterable, Optional

from flask import Response

from ..common.sse import chunks_to_sse, sse_to_events


class ResponseAdapter:
    """Handle post-request adaptation from Azure Responses API to Flask.

    Translates Azure SSE events into OpenAI Chat Completions chunks, including
    reasoning <think> tags and function call streaming. Direct /v1/responses
    streams are passed through.
    """

    # Per-request chat completion id (for streaming)
    _chat_completion_id: Optional[str] = None

    def __init__(self, adapter: Any) -> None:
        """Initialize the adapter with a reference to the AzureAdapter."""
        self.adapter = adapter  # AzureAdapter instance for shared config/env

    # ---- Helpers ----
    @staticmethod
    def _create_chat_completion_id() -> str:
        """Return a new pseudo-random chat completion id."""
        alphabet = ascii_letters + digits
        return "chatcmpl-" + "".join(random.choices(alphabet, k=24))

    @staticmethod
    def _filter_response_headers(
        headers: Dict[str, str], *, streaming: bool
    ) -> Dict[str, str]:
        """Filter hop-by-hop and incompatible headers for downstream responses."""
        # Minimal hop-by-hop headers list for downstream filtering
        hop_by_hop_headers = {
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailers",
            "transfer-encoding",
            "upgrade",
        }
        out: Dict[str, str] = {}
        for k, v in headers.items():
            if k.lower() in hop_by_hop_headers:
                continue
            if streaming and k.lower() == "content-length":
                continue
            out[k] = v
        return out

    def _build_completion_chunk(
        self,
        *,
        delta: Optional[Dict[str, Any]] = None,
        finish_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build a Chat Completions chunk dict with the provided delta."""
        return {
            "id": self._chat_completion_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": self.adapter.inbound_model,
            "choices": [
                {
                    "index": 0,
                    "delta": delta or {},
                    "finish_reason": finish_reason,
                }
            ],
        }

    # ---- Event handlers (per SSE event) ----
    def _output_item__added(
        self, obj: Optional[Dict[str, Any]]
    ) -> Iterable[Dict[str, Any]]:
        """Handle response.output_item.added events and emit chunks as needed."""
        if not isinstance(obj, dict):
            return []
        item_type = obj.get("item", {}).get("type")
        if item_type == "reasoning":
            # Mark that we should open <think> on first reasoning delta
            self._started_thinking = True
            return []
        if item_type == "function_call":
            out: list[Dict[str, Any]] = []
            if getattr(self, "_thinking", False):
                out.append(
                    self._build_completion_chunk(
                        delta={"role": "assistant", "content": "</think>\n\n"}
                    )
                )
                self._thinking = False
            name = obj.get("item", {}).get("name")
            arguments = obj.get("item", {}).get("arguments")
            call_id = obj.get("item", {}).get("call_id")
            out.append(
                self._build_completion_chunk(
                    delta={
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": call_id or "",
                                "type": "function",
                                "function": {
                                    "name": name or "",
                                    "arguments": arguments or "",
                                },
                            }
                        ],
                    }
                )
            )
            self._called_function = True
            return out
        return []

    def _function_call_arguments__delta(
        self, obj: Optional[Dict[str, Any]]
    ) -> Iterable[Dict[str, Any]]:
        """Handle response.function_call.arguments.delta events."""
        out: list[Dict[str, Any]] = []
        if getattr(self, "_thinking", False):
            out.append(
                self._build_completion_chunk(
                    delta={"role": "assistant", "content": "</think>\n\n"}
                )
            )
            self._thinking = False
        arguments_delta = obj.get("delta", "") if isinstance(obj, dict) else ""
        out.append(
            self._build_completion_chunk(
                delta={
                    "tool_calls": [
                        {"index": 0, "function": {"arguments": arguments_delta}}
                    ]
                }
            )
        )
        return out

    def _output_item__done(
        self, obj: Optional[Dict[str, Any]]
    ) -> Optional[Iterable[Dict[str, Any]]]:
        """Handle response.output_item.done events (no-op for completions)."""
        # No-op for completions mapping
        return None

    def _reasoning_summary_text__delta(
        self, obj: Optional[Dict[str, Any]]
    ) -> Iterable[Dict[str, Any]]:
        """Handle reasoning.summary_text.delta events and emit text chunks."""
        out: list[Dict[str, Any]] = []
        if getattr(self, "_started_thinking", False):
            out.append(
                self._build_completion_chunk(
                    delta={"role": "assistant", "content": "<think>"}
                )
            )
            self._thinking = True
            self._started_thinking = False
        out.append(
            self._build_completion_chunk(
                delta={
                    "role": "assistant",
                    "content": (obj.get("delta", "") if isinstance(obj, dict) else ""),
                }
            )
        )
        return out

    def _reasoning_summary_text__done(
        self, obj: Optional[Dict[str, Any]]
    ) -> Iterable[Dict[str, Any]]:
        """Handle reasoning.summary_text.done events and close think block."""
        return [
            self._build_completion_chunk(delta={"role": "assistant", "content": "\n\n"})
        ]

    def _output_text__delta(
        self, obj: Optional[Dict[str, Any]]
    ) -> Iterable[Dict[str, Any]]:
        """Handle response.output_text.delta events and emit text chunks."""
        out: list[Dict[str, Any]] = []
        if getattr(self, "_thinking", False):
            out.append(
                self._build_completion_chunk(
                    delta={"role": "assistant", "content": "</think>\n\n"}
                )
            )
            self._thinking = False
        out.append(
            self._build_completion_chunk(
                delta={
                    "role": "assistant",
                    "content": (obj.get("delta", "") if isinstance(obj, dict) else ""),
                }
            )
        )
        return out

    def adapt(self, upstream_resp: Any) -> Response:
        """Adapt an upstream Azure streaming response into SSE for Flask."""

        def generate() -> Iterable[bytes]:
            # Generate once per stream
            self._chat_completion_id = self._create_chat_completion_id()
            # Initialize per-stream state on the instance
            self._started_thinking = False
            self._thinking = False
            self._called_function = False

            def gen_dicts() -> Iterable[Dict[str, Any]]:
                try:
                    for ev in sse_to_events(
                        upstream_resp.iter_content(chunk_size=8192)
                    ):
                        if ev.is_done:
                            # Upstream [DONE] sentinel
                            continue
                        handler_name = "_" + (ev.event or "").replace(
                            "response.", ""
                        ).replace(".", "__")
                        handler = getattr(self, handler_name, None)
                        if not handler:
                            continue
                        res = handler(ev.json)
                        if res is not None:
                            for chunk in res:
                                yield chunk
                finally:
                    # Emit finish reason at the end of stream
                    if getattr(self, "_called_function", False):
                        yield self._build_completion_chunk(finish_reason="tool_calls")
                    else:
                        yield self._build_completion_chunk(finish_reason="stop")

            # Wrap as SSE with [DONE]
            try:
                yield from chunks_to_sse(gen_dicts())
            finally:
                try:
                    upstream_resp.close()
                except Exception:
                    pass

        headers = self._filter_response_headers(
            dict(getattr(upstream_resp, "headers", {})), streaming=True
        )
        headers["Content-Type"] = "text/event-stream; charset=utf-8"
        headers.pop("Content-Length", None)
        headers["Cache-Control"] = "no-cache"
        headers["Connection"] = "keep-alive"
        headers["X-Accel-Buffering"] = "no"
        return Response(
            generate(),
            status=getattr(upstream_resp, "status_code", 200),
            headers=headers,
        )
