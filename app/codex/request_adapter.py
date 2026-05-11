"""Cursor request adaptation for the Codex provider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .settings import CodexSettings


class UnsupportedCursorShape(RuntimeError):
    """The downstream request is not a supported Cursor request shape."""


@dataclass(frozen=True)
class AdaptedRequest:
    """Codex upstream request body plus routing identity."""

    body: dict[str, Any]
    session_id: str | None
    thread_id: str | None


class CursorRequestAdapter:
    """Convert Cursor OpenAI-compatible requests to Codex Responses requests."""

    def __init__(self, settings: CodexSettings):
        """Initialize the adapter with Codex settings."""
        self.settings = settings

    def adapt(
        self, path: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> AdaptedRequest:
        """Adapt a Cursor request body for the Codex Responses backend."""
        del path
        if not isinstance(payload, dict):
            raise UnsupportedCursorShape("Cursor request body must be a JSON object.")
        self._validate_model(payload)
        self._validate_cursor_marker(payload, headers)

        if "messages" in payload:
            body = self._chat_to_responses(payload)
        elif "input" in payload:
            body = self._responses_passthrough(payload)
        else:
            raise UnsupportedCursorShape(
                "Unsupported Cursor request shape: missing input or messages."
            )
        self._rewrite_model(body)

        session_id = self._session_identity(payload, headers)
        thread_id = session_id
        if session_id:
            body.setdefault("prompt_cache_key", session_id)
        body["stream"] = True
        body.setdefault("parallel_tool_calls", True)
        body["store"] = False
        return AdaptedRequest(body=body, session_id=session_id, thread_id=thread_id)

    def _validate_model(self, payload: dict[str, Any]) -> None:
        model = payload.get("model")
        if model not in self.settings.supported_models:
            raise UnsupportedCursorShape(
                f"Unsupported model {model!r}. Supported: "
                + ", ".join(self.settings.supported_models)
            )

    def _rewrite_model(self, body: dict[str, Any]) -> None:
        model = body.get("model")
        target = self.settings.model_rewrites.get(model)
        if target:
            body["model"] = target

    def _validate_cursor_marker(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> None:
        if self.settings.discovery_mode:
            return
        if self._session_identity(payload, headers):
            return
        if any(
            "cursor" in key.lower() or "cursor" in value.lower()
            for key, value in headers.items()
        ):
            return
        raise UnsupportedCursorShape(
            "Missing Cursor Request Marker. Enable CODEX_DISCOVERY_MODE for first capture."
        )

    def _session_identity(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> str | None:
        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            for key in (
                "cursorConversationId",
                "conversation_id",
                "thread_id",
                "session_id",
            ):
                value = metadata.get(key)
                if isinstance(value, str) and value:
                    return value
        for key in (
            "x-cursor-conversation-id",
            "x-client-request-id",
            "thread-id",
            "thread_id",
            "session-id",
            "session_id",
        ):
            value = _header_get(headers, key)
            if value:
                return value
        user = payload.get("user")
        return user if isinstance(user, str) and user else None

    def _responses_passthrough(self, payload: dict[str, Any]) -> dict[str, Any]:
        out = dict(payload)
        out.pop("stream_options", None)
        out.pop("metadata", None)
        out.pop("user", None)
        out.pop("prompt_cache_retention", None)
        if not out.get("instructions"):
            out["instructions"] = _default_instructions()
        if isinstance(out.get("input"), str):
            out["input"] = [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": out["input"]}],
                }
            ]
        elif isinstance(out.get("input"), list):
            extra_instructions, input_items = _normalize_responses_input(out["input"])
            if extra_instructions:
                if out["instructions"] == _default_instructions():
                    out["instructions"] = "\n\n".join(extra_instructions)
                else:
                    out["instructions"] = "\n\n".join(
                        [out["instructions"], *extra_instructions]
                    )
            out["input"] = input_items
        return out

    def _chat_to_responses(self, payload: dict[str, Any]) -> dict[str, Any]:
        messages = payload.get("messages")
        if not isinstance(messages, list):
            raise UnsupportedCursorShape(
                "Chat Completions payload must include messages."
            )
        instructions: list[str] = []
        input_items: list[dict[str, Any]] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            content = message.get("content")
            if role in {"system", "developer"}:
                text = _content_to_text(content)
                if text:
                    instructions.append(text)
                continue
            if role == "tool":
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.get("tool_call_id"),
                        "output": _content_to_text(content),
                        "status": "completed",
                    }
                )
                continue
            if role in {"user", "assistant"} and content is not None:
                content_type = "input_text" if role == "user" else "output_text"
                input_items.append(
                    {
                        "role": role,
                        "content": [
                            {"type": content_type, "text": _content_to_text(content)}
                        ],
                    }
                )
            for tool_call in message.get("tool_calls") or []:
                if not isinstance(tool_call, dict):
                    continue
                function = (
                    tool_call.get("function")
                    if isinstance(tool_call.get("function"), dict)
                    else {}
                )
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": tool_call.get("id"),
                        "name": function.get("name"),
                        "arguments": function.get("arguments", ""),
                    }
                )

        out: dict[str, Any] = {
            "model": payload["model"],
            "instructions": (
                "\n\n".join(instructions) if instructions else _default_instructions()
            ),
            "input": input_items,
            "tools": _transform_tools(payload.get("tools")),
            "tool_choice": _transform_tool_choice(payload.get("tool_choice")),
        }
        if isinstance(payload.get("reasoning"), dict):
            out["reasoning"] = payload["reasoning"]
        if isinstance(payload.get("include"), list):
            out["include"] = payload["include"]
        if payload.get("service_tier") is not None:
            out["service_tier"] = payload["service_tier"]
        return out


def _header_get(headers: dict[str, str], key: str) -> str | None:
    for actual, value in headers.items():
        if actual.lower() == key.lower() and value:
            return value
    return None


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") in {"text", "input_text", "output_text"}:
                    parts.append(str(item.get("text", "")))
                elif item.get("type") == "image_url":
                    parts.append("[image]")
                else:
                    parts.append(f"[{item.get('type', 'unknown')}]")
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def _normalize_responses_input(
    items: list[Any],
) -> tuple[list[str], list[dict[str, Any]]]:
    instructions: list[str] = []
    input_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in {"system", "developer"}:
            text = _content_to_text(content)
            if text:
                instructions.append(text)
            continue
        if role in {"user", "assistant"}:
            input_items.append(
                {
                    "role": role,
                    "content": _normalize_content_parts(content, role),
                }
            )
            continue
        input_items.append(dict(item))
    return instructions, input_items


def _normalize_content_parts(content: Any, role: Any) -> list[dict[str, Any]]:
    if isinstance(content, list):
        return [
            _normalize_content_part(part, role)
            for part in content
            if isinstance(part, dict)
        ]
    content_type = "input_text" if role == "user" else "output_text"
    return [{"type": content_type, "text": _content_to_text(content)}]


def _normalize_content_part(part: dict[str, Any], role: Any) -> dict[str, Any]:
    part_type = part.get("type")
    if part_type in {"input_text", "output_text"}:
        return dict(part)
    if part_type == "text":
        content_type = "input_text" if role == "user" else "output_text"
        return {"type": content_type, "text": str(part.get("text", ""))}
    return dict(part)


def _transform_tools(tools: Any) -> list[dict[str, Any]]:
    if not isinstance(tools, list):
        return []
    out: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function")
        if isinstance(function, dict):
            out.append(
                {
                    "type": "function",
                    "name": function.get("name"),
                    "description": function.get("description"),
                    "parameters": function.get("parameters"),
                    "strict": False,
                }
            )
        elif tool.get("name"):
            out.append(dict(tool))
    return out


def _transform_tool_choice(tool_choice: Any) -> Any:
    if not isinstance(tool_choice, dict) or tool_choice.get("type") != "function":
        return tool_choice
    function = tool_choice.get("function")
    if isinstance(function, dict) and function.get("name"):
        return {"type": "function", "name": function["name"]}
    return tool_choice


def _default_instructions() -> str:
    return "You are a coding assistant running through Cursor. Follow the user's request directly."
