"""Response adaptation helpers for Azure Responses API streams.

This module defines ResponseAdapter, which converts Azure SSE streams into
OpenAI Chat Completions-compatible streaming responses.
"""

from __future__ import annotations

import random
import time
from string import ascii_letters, digits
from typing import Any, Dict, Iterable, Optional

from flask import Response, current_app, stream_with_context
from rich.live import Live

from ..common.logging import console, create_message_panel
from ..common.sse import chunks_to_sse, sse_to_events
from ..exceptions import ClientClosedConnection

# Centralized events that should end a <think> block before handling
THINKING_STOP_EVENTS = {"response.output_text.delta", "response.output_item.added"}


class ResponseAdapter:
    """Handle post-request adaptation from Azure Responses API to Flask.

    Translates Azure SSE events into OpenAI Chat Completions chunks, including
    reasoning <think> tags and function call streaming. Direct /v1/responses
    streams are passed through.
    """

    # Per-request chat completion id (for streaming)
    _chat_completion_id: Optional[str]
    _thinking: bool
    _tool_calls: int

    def __init__(self, adapter: Any) -> None:
        """Initialize the adapter with a reference to the AzureAdapter."""
        self.adapter = adapter  # AzureAdapter instance for shared config/env

    # ---- Helpers ----
    @staticmethod
    def _create_chat_completion_id() -> str:
        """Return a new pseudo-random chat completion id."""
        alphabet = ascii_letters + digits
        return "chatcmpl-" + "".join(random.choices(alphabet, k=24))

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
    ) -> Optional[Dict[str, Any]]:
        """Handle response.output_item.added events and emit a single chunk."""

        item_type = obj.get("item", {}).get("type")
        if item_type == "reasoning":
            self._thinking = True
            return self._build_completion_chunk(
                delta={"role": "assistant", "content": "<think>\n\n"}
            )
        if item_type == "function_call":
            self._tool_calls += 1
            name = obj.get("item", {}).get("name")
            arguments = obj.get("item", {}).get("arguments")
            call_id = obj.get("item", {}).get("call_id")
            return self._build_completion_chunk(
                delta={
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "index": self._tool_calls - 1,
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
        return None

    def _function_call_arguments__delta(
        self, obj: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Handle response.function_call.arguments.delta events."""
        arguments_delta = obj.get("delta", "") if isinstance(obj, dict) else ""
        return self._build_completion_chunk(
            delta={
                "tool_calls": [
                    {
                        "index": self._tool_calls - 1,
                        "function": {"arguments": arguments_delta},
                    }
                ]
            }
        )

    def _reasoning_summary_text__delta(
        self, obj: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Handle reasoning.summary_text.delta events and emit text chunk."""
        return self._build_completion_chunk(
            delta={
                "role": "assistant",
                "content": (obj.get("delta", "") if isinstance(obj, dict) else ""),
            }
        )

    def _reasoning_summary_text__done(
        self, obj: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Handle reasoning.summary_text.done events and close with blank line inside think block."""
        return self._build_completion_chunk(
            delta={"role": "assistant", "content": "\n\n"}
        )

    def _output_text__delta(
        self, obj: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Handle response.output_text.delta events and emit text chunk."""
        return self._build_completion_chunk(
            delta={
                "role": "assistant",
                "content": (obj.get("delta", "") if isinstance(obj, dict) else ""),
            }
        )

    def adapt(self, upstream_resp: Any) -> Response:
        """Adapt an upstream Azure streaming response into SSE for Flask."""

        @stream_with_context
        def generate() -> Iterable[bytes]:
            # Generate once per stream
            self._chat_completion_id = self._create_chat_completion_id()
            # Initialize per-stream state on the instance
            self._thinking = False
            self._tool_calls = 0

            def gen_dicts() -> Iterable[Dict[str, Any]]:
                # Initialize message object for completion logging
                completion_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [],
                }

                events = 0
                with Live(
                    None,
                    console=console,
                    refresh_per_second=2,
                ) as live:  # update 4 times a second to feel fluid
                    for ev in sse_to_events(
                        upstream_resp.iter_content(chunk_size=8192)
                    ):
                        if current_app.config["LOG_COMPLETION"]:
                            if events > 1:
                                live.update(create_message_panel(completion_msg, 1, 1))
                            events += 1

                        handler_name = "_" + (ev.event or "").replace(
                            "response.", ""
                        ).replace(".", "__")
                        handler = getattr(self, handler_name, None)
                        if not handler:
                            continue

                        # Centrally close <think> blocks whenever a stop event is seen
                        if self._thinking and (ev.event in THINKING_STOP_EVENTS):
                            yield self._build_completion_chunk(
                                delta={"role": "assistant", "content": "</think>\n\n"}
                            )
                            self._thinking = False

                            if current_app.config["LOG_COMPLETION"]:
                                completion_msg["content"] += "</think>\n\n"

                        res = handler(ev.json)
                        if res is not None:
                            yield res

                            if current_app.config["LOG_COMPLETION"]:
                                delta = res.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content")

                                if content is not None:
                                    # Append content to the message
                                    completion_msg["content"] += content
                                else:
                                    # Handle tool calls
                                    tool_calls_delta = delta.get("tool_calls", [])
                                    for tool_call_delta in tool_calls_delta:
                                        function = tool_call_delta.get("function", {})
                                        name = function.get("name")
                                        arguments = function.get("arguments", "")

                                        if name:
                                            # New tool call - add to the list
                                            completion_msg["tool_calls"].append(
                                                {
                                                    "id": tool_call_delta.get("id", ""),
                                                    "type": "function",
                                                    "function": {
                                                        "name": name,
                                                        "arguments": arguments,
                                                    },
                                                }
                                            )
                                        else:
                                            # Append arguments to the last tool call
                                            completion_msg["tool_calls"][-1][
                                                "function"
                                            ]["arguments"] += arguments

                    if self._tool_calls > 0:
                        yield self._build_completion_chunk(finish_reason="tool_calls")
                    else:
                        yield self._build_completion_chunk(finish_reason="stop")
                    if current_app.config["LOG_COMPLETION"]:
                        live.update(create_message_panel(completion_msg, 1, 1))

            try:
                yield from chunks_to_sse(gen_dicts())
            except GeneratorExit:
                # Downstream client closed the connection mid-stream
                # Translate to a clearer exception; upstream will be closed in finally
                raise ClientClosedConnection(
                    "Client closed connection during streaming response"
                ) from None
            finally:
                upstream_resp.close()

        headers = {}
        headers["Content-Type"] = "text/event-stream; charset=utf-8"
        headers["Cache-Control"] = "no-cache"
        headers["Connection"] = "keep-alive"
        headers["X-Accel-Buffering"] = "no"
        return Response(
            generate(),
            status=getattr(upstream_resp, "status_code", 200),
            headers=headers,
        )
