"""Codex Responses SSE to Chat Completions SSE adaptation."""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from string import ascii_letters, digits
from typing import Any, Iterable, Iterator

THINKING_STOP_EVENTS = {"response.output_text.delta", "response.output_item.added"}


@dataclass
class SSEEvent:
    """Parsed Server-Sent Event."""

    event: str | None
    data: str

    @property
    def json(self) -> Any | None:
        """Return parsed JSON data for this SSE event."""
        text = self.data.strip()
        if not text or text == "[DONE]":
            return None
        return json.loads(text)


class SSEDecoder:
    """Small SSE decoder without Flask recording side effects."""

    def __init__(self) -> None:
        """Initialize decoder buffers."""
        self.buffer = b""
        self.lines: list[bytes] = []

    def feed(self, chunk: bytes) -> list[SSEEvent]:
        """Feed bytes into the decoder and return complete events."""
        self.buffer += chunk
        events: list[SSEEvent] = []
        while True:
            index = self.buffer.find(b"\n")
            if index == -1:
                break
            line = self.buffer[: index + 1]
            self.buffer = self.buffer[index + 1 :]
            stripped = line.rstrip(b"\r\n")
            if not stripped:
                events.append(self._parse(self.lines))
                self.lines = []
            else:
                self.lines.append(stripped)
        return events

    def flush(self) -> list[SSEEvent]:
        """Flush a trailing event when the stream ends mid-message."""
        if not self.lines:
            return []
        event = self._parse(self.lines)
        self.lines = []
        return [event]

    def _parse(self, lines: list[bytes]) -> SSEEvent:
        event_name: str | None = None
        data_parts: list[bytes] = []
        for line in lines:
            if line.startswith(b"event:"):
                event_name = line.split(b":", 1)[1].strip().decode(errors="replace")
            elif line.startswith(b"data:"):
                data_parts.append(line[5:].strip())
        return SSEEvent(
            event=event_name,
            data=b"\n".join(data_parts).decode(errors="replace"),
        )


class ChatSSEAdapter:
    """Translate Codex Responses SSE events into Chat Completions chunks."""

    def __init__(self, model: str):
        """Initialize stream state for one chat response."""
        self.model = model
        self.chat_id = _chat_completion_id()
        self.thinking = False
        self.tool_calls = 0
        self.usage: dict[str, Any] | None = None

    def handle(self, event: SSEEvent) -> list[dict[str, Any]]:
        """Handle one upstream SSE event."""
        event_name = event.event or ""
        obj = event.json
        chunks: list[dict[str, Any]] = []
        if self.thinking and event_name in THINKING_STOP_EVENTS:
            chunks.append(
                self._chunk(delta={"role": "assistant", "content": "</think>\n\n"})
            )
            self.thinking = False

        if event_name == "response.output_item.added":
            chunk = self._output_item_added(obj)
        elif event_name in {
            "response.output_text.delta",
            "response.refusal.delta",
            "response.audio.transcript.delta",
            "response.code_interpreter_call_code.delta",
            "response.reasoning_text.delta",
            "response.reasoning_summary_text.delta",
        }:
            chunk = self._text_delta(obj)
        elif event_name in {
            "response.function_call_arguments.delta",
            "response.custom_tool_call_input.delta",
            "response.mcp_call_arguments.delta",
        }:
            chunk = self._tool_arguments_delta(obj)
        elif event_name == "response.completed":
            self._capture_usage(obj)
            chunk = None
        elif event_name == "response.failed":
            chunk = self._failed(obj)
        elif event_name == "response.incomplete":
            chunk = self._incomplete(obj)
        else:
            chunk = None

        if chunk is not None:
            chunks.append(chunk)
        return chunks

    def finish(self) -> list[dict[str, Any]]:
        """Build terminal chunks."""
        finish_reason = "tool_calls" if self.tool_calls else "stop"
        chunks = [self._chunk(finish_reason=finish_reason)]
        usage = self._usage_chunk()
        if usage is not None:
            chunks.append(usage)
        return chunks

    def _chunk(
        self,
        *,
        delta: dict[str, Any] | None = None,
        finish_reason: str | None = None,
    ) -> dict[str, Any]:
        return {
            "id": self.chat_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": self.model,
            "choices": [
                {
                    "index": 0,
                    "delta": delta or {},
                    "finish_reason": finish_reason,
                }
            ],
        }

    def _output_item_added(self, obj: Any) -> dict[str, Any] | None:
        item = obj.get("item", {}) if isinstance(obj, dict) else {}
        item_type = item.get("type")
        if item_type == "reasoning":
            self.thinking = True
            return self._chunk(delta={"role": "assistant", "content": "<think>\n\n"})
        if item_type in {"function_call", "custom_tool_call"}:
            self.tool_calls += 1
            return self._chunk(
                delta={
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "index": self.tool_calls - 1,
                            "id": item.get("call_id") or item.get("id") or "",
                            "type": "function",
                            "function": {
                                "name": item.get("name") or "",
                                "arguments": item.get("arguments")
                                or item.get("input")
                                or "",
                            },
                        }
                    ],
                }
            )
        return None

    def _text_delta(self, obj: Any) -> dict[str, Any]:
        delta = obj.get("delta", "") if isinstance(obj, dict) else ""
        return self._chunk(delta={"role": "assistant", "content": delta})

    def _tool_arguments_delta(self, obj: Any) -> dict[str, Any] | None:
        if self.tool_calls < 1:
            return None
        delta = obj.get("delta", "") if isinstance(obj, dict) else ""
        return self._chunk(
            delta={
                "tool_calls": [
                    {
                        "index": self.tool_calls - 1,
                        "function": {"arguments": delta},
                    }
                ]
            }
        )

    def _capture_usage(self, obj: Any) -> None:
        response = obj.get("response", {}) if isinstance(obj, dict) else {}
        usage = response.get("usage")
        self.usage = usage if isinstance(usage, dict) else None

    def _usage_chunk(self) -> dict[str, Any] | None:
        if not isinstance(self.usage, dict):
            return None
        input_details = self.usage.get("input_tokens_details")
        output_details = self.usage.get("output_tokens_details")
        return {
            "id": self.chat_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": self.model,
            "choices": [],
            "usage": {
                "prompt_tokens": self.usage.get("input_tokens", 0),
                "completion_tokens": self.usage.get("output_tokens", 0),
                "total_tokens": self.usage.get("total_tokens", 0),
                "prompt_tokens_details": {
                    "cached_tokens": (
                        input_details.get("cached_tokens", 0)
                        if isinstance(input_details, dict)
                        else 0
                    ),
                },
                "completion_tokens_details": {
                    "reasoning_tokens": (
                        output_details.get("reasoning_tokens", 0)
                        if isinstance(output_details, dict)
                        else 0
                    ),
                },
            },
        }

    def _failed(self, obj: Any) -> dict[str, Any]:
        response = obj.get("response", {}) if isinstance(obj, dict) else {}
        error = response.get("error", {}) if isinstance(response, dict) else {}
        message = error.get("message", "Upstream response failed.")
        return self._chunk(delta={"role": "assistant", "content": message})

    def _incomplete(self, obj: Any) -> dict[str, Any]:
        response = obj.get("response", {}) if isinstance(obj, dict) else {}
        details = (
            response.get("incomplete_details", {}) if isinstance(response, dict) else {}
        )
        reason = (
            details.get("reason", "unknown") if isinstance(details, dict) else "unknown"
        )
        return self._chunk(
            delta={
                "role": "assistant",
                "content": f"\n\n[Response was truncated: {reason}]",
            }
        )


def adapt_responses_sse_to_chat_sse(
    chunks: Iterable[bytes], *, model: str
) -> Iterator[bytes]:
    """Adapt an upstream Responses SSE byte stream to Chat Completions SSE."""
    decoder = SSEDecoder()
    adapter = ChatSSEAdapter(model)
    for chunk in chunks:
        for event in decoder.feed(chunk):
            for message in adapter.handle(event):
                yield _encode_sse(message)
    for event in decoder.flush():
        for message in adapter.handle(event):
            yield _encode_sse(message)
    for message in adapter.finish():
        yield _encode_sse(message)
    yield b"data: [DONE]\n\n"


def _encode_sse(obj: dict[str, Any]) -> bytes:
    return (
        b"data: "
        + json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()
        + b"\n\n"
    )


def _chat_completion_id() -> str:
    alphabet = ascii_letters + digits
    return "chatcmpl-" + "".join(random.choices(alphabet, k=24))
