"""Unit tests for Codex response adaptation."""

import json

from app.codex.response_adapter import adapt_responses_sse_to_chat_sse


def _sse(event_name, payload):
    return (
        f"event: {event_name}\n"
        f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
    ).encode()


def _messages(*chunks):
    body = b"".join(adapt_responses_sse_to_chat_sse(chunks, model="gpt-5.4")).decode()
    out = []
    for raw_message in body.strip().split("\n\n"):
        data = "\n".join(
            line[len("data: ") :]
            for line in raw_message.splitlines()
            if line.startswith("data: ")
        )
        if data == "[DONE]":
            out.append("[DONE]")
        elif data:
            out.append(json.loads(data))
    return out


def test_codex_adapts_output_text_to_chat_completion_chunks():
    """Output text deltas become Chat Completions chunks."""
    messages = _messages(
        _sse(
            "response.output_text.delta",
            {"type": "response.output_text.delta", "delta": "hi"},
        ),
        _sse(
            "response.completed",
            {"type": "response.completed", "response": {"usage": None}},
        ),
    )

    assert messages[0]["object"] == "chat.completion.chunk"
    assert messages[0]["model"] == "gpt-5.4"
    assert messages[0]["choices"][0]["delta"] == {
        "role": "assistant",
        "content": "hi",
    }
    assert messages[-2]["choices"][0]["finish_reason"] == "stop"
    assert messages[-1] == "[DONE]"


def test_codex_adapts_reasoning_inside_think_tags():
    """Reasoning deltas are wrapped in think tags."""
    messages = _messages(
        _sse(
            "response.output_item.added",
            {"type": "response.output_item.added", "item": {"type": "reasoning"}},
        ),
        _sse(
            "response.reasoning_summary_text.delta",
            {"type": "response.reasoning_summary_text.delta", "delta": "thinking"},
        ),
        _sse(
            "response.output_text.delta",
            {"type": "response.output_text.delta", "delta": "answer"},
        ),
    )

    content = [msg["choices"][0]["delta"].get("content") for msg in messages[:-1]]
    assert content[:4] == ["<think>\n\n", "thinking", "</think>\n\n", "answer"]


def test_codex_adapts_function_call_stream():
    """Function call argument streams become Chat tool call chunks."""
    messages = _messages(
        _sse(
            "response.output_item.added",
            {
                "type": "response.output_item.added",
                "item": {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "Shell",
                    "arguments": "",
                },
            },
        ),
        _sse(
            "response.function_call_arguments.delta",
            {"type": "response.function_call_arguments.delta", "delta": '{"cmd"'},
        ),
        _sse(
            "response.function_call_arguments.delta",
            {"type": "response.function_call_arguments.delta", "delta": ':"ls"}'},
        ),
    )

    first = messages[0]["choices"][0]["delta"]["tool_calls"][0]
    second = messages[1]["choices"][0]["delta"]["tool_calls"][0]
    assert first["id"] == "call_1"
    assert first["function"]["name"] == "Shell"
    assert second["function"]["arguments"] == '{"cmd"'
    assert messages[-2]["choices"][0]["finish_reason"] == "tool_calls"
