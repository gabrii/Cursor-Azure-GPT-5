"""Unit tests for Azure response adaptation."""

import json

from app.azure.adapter import AzureAdapter


class _FakeUpstreamResponse:
    """Minimal streaming response stub for ResponseAdapter tests."""

    status_code = 200

    def __init__(self, chunks):
        self._chunks = chunks
        self.closed = False

    def iter_content(self, chunk_size=8192):
        del chunk_size
        yield from self._chunks

    def close(self):
        self.closed = True


def _sse(event_name, payload):
    """Build a single SSE event payload."""
    return (
        f"event: {event_name}\n"
        f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
    ).encode("utf-8")


def test_response_adapter_emits_usage_chunk(app):
    """Emit a terminal usage chunk when Azure reports final token usage."""
    adapter = AzureAdapter()
    adapter.inbound_model = "gpt-5.4"
    adapter.include_usage = True

    upstream = _FakeUpstreamResponse(
        [
            _sse(
                "response.created",
                {
                    "type": "response.created",
                    "response": {
                        "id": "resp_123",
                        "usage": None,
                    },
                },
            ),
            _sse(
                "response.output_item.added",
                {
                    "type": "response.output_item.added",
                    "item": {"type": "message"},
                },
            ),
            _sse(
                "response.output_text.delta",
                {
                    "type": "response.output_text.delta",
                    "delta": "pong",
                },
            ),
            _sse(
                "response.completed",
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp_123",
                        "usage": {
                            "input_tokens": 11,
                            "output_tokens": 7,
                            "total_tokens": 18,
                        },
                    },
                },
            ),
        ]
    )

    response = adapter.response_adapter.adapt(upstream)
    body = b"".join(response.response).decode("utf-8")

    messages = []
    for raw_message in body.strip().split("\n\n"):
        data_lines = [
            line[len("data: ") :]
            for line in raw_message.splitlines()
            if line.startswith("data: ")
        ]
        if not data_lines:
            continue
        data = "\n".join(data_lines)
        if data == "[DONE]":
            continue
        messages.append(json.loads(data))

    assert messages[-1] == {
        "id": messages[-1]["id"],
        "object": "chat.completion.chunk",
        "created": messages[-1]["created"],
        "model": "gpt-5.4",
        "choices": [],
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
        },
    }
    assert upstream.closed is True
