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

# Events we intentionally skip without logging (pure lifecycle / status noise)
_SILENT_EVENTS = {
    "response.created",
    "response.in_progress",
    "response.queued",
    "response.completed",
    "response.output_item.done",
    "response.output_text.done",
    "response.content_part.added",
    "response.content_part.done",
    "response.function_call_arguments.done",
    "response.reasoning_text.done",
    "response.reasoning_summary_part.added",
    "response.reasoning_summary_part.done",
    "response.refusal.done",
    "response.output_text.annotation.added",
    # Tool status events (progress / searching / interpreting)
    "response.file_search_call.in_progress",
    "response.file_search_call.searching",
    "response.file_search_call.completed",
    "response.web_search_call.in_progress",
    "response.web_search_call.searching",
    "response.web_search_call.completed",
    "response.code_interpreter_call.in_progress",
    "response.code_interpreter_call.interpreting",
    "response.code_interpreter_call.completed",
    "response.image_generation_call.in_progress",
    "response.image_generation_call.generating",
    "response.image_generation_call.completed",
    "response.image_generation_call.partial_image",
    "response.mcp_call.in_progress",
    "response.mcp_call.completed",
    "response.mcp_list_tools.in_progress",
    "response.mcp_list_tools.completed",
    "response.audio.done",
    "response.audio.transcript.done",
}


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
    _usage: Optional[Dict[str, Any]]

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

    def _build_usage_chunk(self) -> Optional[Dict[str, Any]]:
        """Build a terminal Chat Completions usage chunk."""
        if not isinstance(self._usage, dict):
            return None

        return {
            "id": self._chat_completion_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": self.adapter.inbound_model,
            "choices": [],
            "usage": {
                "prompt_tokens": self._usage.get("input_tokens", 0),
                "completion_tokens": self._usage.get("output_tokens", 0),
                "total_tokens": self._usage.get("total_tokens", 0),
            },
        }

    # ---- Helpers for native Responses API tool types ----
    def _native_tool_to_function_call(
        self, item: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Convert a native Responses API tool call item into a Chat Completions tool_calls chunk.

        Handles native tool types (apply_patch_call, shell_call, mcp_call, etc.)
        by wrapping them as function calls so Cursor can process them.
        """
        import json as _json

        item_type = item.get("type", "")
        call_id = item.get("call_id") or item.get("id") or ""

        # Map native type to a function name Cursor expects
        native_type_to_name = {
            "apply_patch_call": "ApplyPatch",
            "shell_call": "Shell",
            "local_shell_call": "Shell",
            "mcp_call": "CallMcpTool",
            "computer_call": "ComputerUse",
        }

        name = native_type_to_name.get(item_type)
        if not name:
            return None

        from ..common.logging import console

        console.print(
            f"[bold magenta]NATIVE TOOL:[/bold magenta] Converting {item_type} → {name} "
            f"(call_id={call_id})"
        )

        # Build the arguments JSON from the item's fields
        if item_type == "apply_patch_call":
            # Extract diff/operation from the native format
            operation = item.get("operation", {})
            args = {
                "diff": operation.get("diff", ""),
                "path": operation.get("path", ""),
            }
        elif item_type in ("shell_call", "local_shell_call"):
            action = item.get("action", {})
            args = {
                "command": action.get("command", []),
                "working_directory": action.get("working_directory", ""),
            }
        elif item_type == "mcp_call":
            args = {
                "server_label": item.get("server_label", ""),
                "tool_name": item.get("name", ""),
                "arguments": item.get("arguments", "{}"),
            }
        else:
            args = {}

        arguments_json = _json.dumps(args, ensure_ascii=False)

        self._tool_calls += 1
        return self._build_completion_chunk(
            delta={
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "index": self._tool_calls - 1,
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": arguments_json,
                        },
                    }
                ],
            }
        )

    # ---- Event handlers (per SSE event) ----
    def _output_item__added(
        self, obj: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Handle response.output_item.added events and emit a single chunk."""

        item = obj.get("item", {}) if isinstance(obj, dict) else {}
        item_type = item.get("type")

        if item_type == "reasoning":
            self._thinking = True
            return self._build_completion_chunk(
                delta={"role": "assistant", "content": "<think>\n\n"}
            )
        if item_type == "function_call":
            self._tool_calls += 1
            name = item.get("name")
            arguments = item.get("arguments")
            call_id = item.get("call_id")
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
        # Handle custom_tool_call — Cursor's tools come through as this type
        if item_type == "custom_tool_call":
            self._tool_calls += 1
            name = item.get("name", "")
            call_id = item.get("call_id") or item.get("id") or ""
            # In streaming, `input` is empty here; deltas arrive via
            # response.custom_tool_call_input.delta events.
            arguments = item.get("input", "")
            return self._build_completion_chunk(
                delta={
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "index": self._tool_calls - 1,
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": arguments,
                            },
                        }
                    ],
                }
            )

        # Handle native Responses API tool types (apply_patch_call, shell_call, etc.)
        if item_type in (
            "apply_patch_call",
            "shell_call",
            "local_shell_call",
            "mcp_call",
            "computer_call",
        ):
            return self._native_tool_to_function_call(item)

        if item_type == "message":
            # Message items (e.g. output_item.added with type=message) are typically
            # the container for output text. No action needed here.
            return None

        # Log unexpected item types for debugging
        if item_type:
            from ..common.logging import console

            console.print(f"[bold yellow]UNKNOWN ITEM TYPE:[/bold yellow] {item_type}")

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

    def _custom_tool_call_input__delta(
        self, obj: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Handle response.custom_tool_call_input.delta events (streaming tool arguments)."""
        input_delta = obj.get("delta", "") if isinstance(obj, dict) else ""
        return self._build_completion_chunk(
            delta={
                "tool_calls": [
                    {
                        "index": self._tool_calls - 1,
                        "function": {"arguments": input_delta},
                    }
                ]
            }
        )

    def _custom_tool_call_input__done(
        self, obj: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Handle response.custom_tool_call_input.done — end marker, no-op."""
        self._custom_tool_input_buf = ""
        return None

    # ---- Error event (no "response." prefix!) ----
    def _error(self, obj: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Handle 'error' SSE event by logging until response.failed arrives."""
        code = obj.get("code", "") if isinstance(obj, dict) else ""
        message = obj.get("message", "") if isinstance(obj, dict) else ""
        from ..common.logging import console as _err_console

        _err_console.print(
            f"[bold red]STREAM ERROR:[/bold red] code={code} message={message}"
        )
        return None

    # ---- Refusal events ----
    def _refusal__delta(
        self, obj: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Handle response.refusal.delta — model is refusing the request."""
        return self._build_completion_chunk(
            delta={
                "role": "assistant",
                "content": (obj.get("delta", "") if isinstance(obj, dict) else ""),
            }
        )

    # ---- Reasoning text (raw, not summary) ----
    def _reasoning_text__delta(
        self, obj: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Handle response.reasoning_text.delta — raw reasoning content.

        We emit this inside <think> tags the same way we do summaries.
        """
        return self._build_completion_chunk(
            delta={
                "role": "assistant",
                "content": (obj.get("delta", "") if isinstance(obj, dict) else ""),
            }
        )

    # ---- MCP call argument streaming ----
    def _mcp_call_arguments__delta(
        self, obj: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Handle response.mcp_call_arguments.delta — streaming MCP tool args."""
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

    def _mcp_call_arguments__done(
        self, obj: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Handle response.mcp_call_arguments.done — no-op end marker."""
        return None

    # ---- MCP call failure ----
    def _mcp_call__failed(
        self, obj: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Handle response.mcp_call.failed — log MCP call failure."""
        from ..common.logging import console as _mcp_console

        _mcp_console.print(f"[bold red]MCP CALL FAILED:[/bold red] {str(obj)[:300]}")
        return None

    # ---- MCP list tools failure ----
    def _mcp_list_tools__failed(
        self, obj: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Handle response.mcp_list_tools.failed — log MCP list failure."""
        from ..common.logging import console as _mcp_lt_console

        _mcp_lt_console.print(
            f"[bold red]MCP LIST TOOLS FAILED:[/bold red] {str(obj)[:300]}"
        )
        return None

    # ---- Code interpreter code streaming ----
    def _code_interpreter_call_code__delta(
        self, obj: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Handle response.code_interpreter_call_code.delta — streaming code."""
        # Emit as text content so the user sees the code being generated
        return self._build_completion_chunk(
            delta={
                "role": "assistant",
                "content": (obj.get("delta", "") if isinstance(obj, dict) else ""),
            }
        )

    # ---- Audio events ----
    def _audio__delta(self, obj: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Handle response.audio.delta — audio chunk (base64). Pass-through as-is."""
        # Audio can't be represented in Chat Completions text stream; skip.
        return None

    def _audio__transcript__delta(
        self, obj: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Handle response.audio.transcript.delta — audio transcript text."""
        return self._build_completion_chunk(
            delta={
                "role": "assistant",
                "content": (obj.get("delta", "") if isinstance(obj, dict) else ""),
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

    def _completed(self, obj: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Capture final Azure usage for an optional terminal usage chunk."""
        response = obj.get("response", {}) if isinstance(obj, dict) else {}
        usage = response.get("usage")
        self._usage = usage if isinstance(usage, dict) else None
        return None

    def _incomplete(self, obj: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Handle response.incomplete events (model output was truncated).

        This occurs when the model hits max_output_tokens. We log and pass
        the reason through so the downstream client knows the response was cut short.
        """
        from ..common.logging import console as _inc_console

        reason = (
            obj.get("response", {})
            .get("incomplete_details", {})
            .get("reason", "unknown")
            if isinstance(obj, dict)
            else "unknown"
        )
        _inc_console.print(f"[bold red]RESPONSE INCOMPLETE:[/bold red] reason={reason}")
        return self._build_completion_chunk(
            delta={
                "role": "assistant",
                "content": f"\n\n[Response was truncated: {reason}]",
            }
        )

    def _failed(self, obj: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Handle response.failed events and emit a single chunk."""
        error = obj.get("response", {}).get("error", {})
        return self._build_completion_chunk(
            delta={
                "role": "assistant",
                "content": "Azure raised a '"
                + error.get("code", "")
                + "' error with the following message:\n\n\n"
                + "_**"
                + error.get("message", "")
                + "**_\n\n\n"
                "This might be a genuine error on Azure's side and not a problem of Cursor-Azure-GPT-5.",
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
            self._usage = None

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

                        # Dispatch: strip "response." prefix, replace "." with "__"
                        # Special case: "error" has no "response." prefix
                        raw_event = ev.event or ""
                        handler_name = "_" + raw_event.replace(
                            "response.", "", 1  # only strip the first occurrence
                        ).replace(".", "__")
                        handler = getattr(self, handler_name, None)
                        if not handler:
                            # Log ALL unhandled events so nothing is silently dropped
                            from ..common.logging import console as _evt_console

                            # Suppress noisy lifecycle events we intentionally skip
                            if raw_event not in _SILENT_EVENTS:
                                _evt_console.print(
                                    f"[bold yellow]UNHANDLED EVENT:[/bold yellow] "
                                    f"{raw_event} → {handler_name} "
                                    f"data={str(ev.json)[:300]}"
                                )
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

                    finish = "tool_calls" if self._tool_calls > 0 else "stop"
                    from ..common.logging import console as _log_console

                    _log_console.print(
                        f"[bold cyan]STREAM_END:[/bold cyan] events={events}, "
                        f"tool_calls={self._tool_calls}, finish_reason={finish}"
                    )
                    if self._tool_calls > 0:
                        yield self._build_completion_chunk(finish_reason="tool_calls")
                    else:
                        yield self._build_completion_chunk(finish_reason="stop")
                    if self.adapter.include_usage:
                        usage_chunk = self._build_usage_chunk()
                        if usage_chunk is not None:
                            yield usage_chunk
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
