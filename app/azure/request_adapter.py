"""Request adaptation helpers for Azure Responses API.

This module defines RequestAdapter, which transforms incoming OpenAI-style
requests into Azure Responses API request parameters.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from flask import Request, current_app

from ..exceptions import ServiceConfigurationError
from .model_config import resolve_model_settings


class RequestAdapter:
    """Handle pre-request adaptation for the Azure Responses API.

    Transforms OpenAI Completions/Chat-style inputs into Azure Responses API
    request parameters suitable for streaming completions in this codebase.
    Returns request_kwargs for requests.request(**kwargs). Also sets
    per-request state on the adapter (model).
    """

    def __init__(self, adapter: Any) -> None:
        """Initialize the adapter with a reference to the AzureAdapter."""
        self.adapter = adapter  # AzureAdapter instance for shared config/env

    # ---- Helpers (kept local to minimize cross-module coupling) ----
    def _copy_request_headers_for_azure(
        self, src: Request, *, api_key: str
    ) -> Dict[str, str]:
        headers: Dict[str, str] = {k: v for k, v in src.headers.items()}
        headers.pop("Host", None)
        # Azure prefers api-key header
        headers.pop("Authorization", None)
        headers["api-key"] = api_key
        return headers

    def _messages_to_responses_input_and_instructions(
        self, messages: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        instructions_parts: List[str] = []
        input_items: List[Dict[str, Any]] = []

        def normalize_content(content: Any) -> str:
            if content is None:
                return ""
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts: List[str] = []
                for part in content:
                    if isinstance(part, str):
                        parts.append(part)
                        continue
                    if isinstance(part, dict):
                        text = part.get("text")
                        if text is not None:
                            parts.append(str(text))
                        elif "content" in part:
                            parts.append(str(part.get("content")))
                        else:
                            parts.append(json.dumps(part, ensure_ascii=False))
                        continue
                    parts.append(str(part))
                return "\n".join([p for p in parts if p])
            if isinstance(content, dict):
                if "text" in content:
                    return str(content.get("text"))
                if "content" in content:
                    return str(content.get("content"))
                return json.dumps(content, ensure_ascii=False)
            return str(content)

        for m in messages:
            role = m.get("role")
            content = normalize_content(m.get("content"))
            if role in {"system", "developer"}:
                instructions_parts.append(content)
                continue
            # For user/assistant/tools as inputs
            if role == "tool":
                call_id = m.get("tool_call_id")

                item = {
                    "type": "function_call_output",
                    "output": content,
                    "status": "completed",
                    "call_id": call_id,
                }
                input_items.append(item)
            else:
                item = {
                    "role": role or "user",
                    "content": [
                        {
                            "type": "input_text" if role == "user" else "output_text",
                            "text": content,
                        },
                    ],
                }
                input_items.append(item)

                if tool_calls := m.get("tool_calls"):
                    for tool_call in tool_calls:
                        function = tool_call.get("function", {})
                        call_id = tool_call.get("id")
                        item = {
                            "type": "function_call",
                            "name": function.get("name"),
                            "arguments": function.get("arguments"),
                            "call_id": call_id,
                        }
                        input_items.append(item)

        instructions = "\n\n".join(instructions_parts) if instructions_parts else None
        return {
            "instructions": instructions,
            "input": input_items if input_items else None,
        }

    def _transform_tools_for_responses(self, tools: Any) -> Any:
        """Normalize downstream tools into Responses-style tools.

        Our replay fixtures expect Responses tool format (with `input_schema`).
        Some downstream clients may still send OpenAI function tools
        (with `parameters`). We convert those.
        """
        if tools is None:
            return []

        if not isinstance(tools, list):
            current_app.logger.debug(
                "Skipping tools because tools payload is not a list: %r",
                tools,
            )
            return []

        out: List[Dict[str, Any]] = []
        for t in tools:
            if not isinstance(t, dict):
                continue

            # Pass through if already Responses-style.
            if "input_schema" in t and t.get("type") == "function":
                out.append(t)
                continue

            # Convert OpenAI function tool shape -> Responses tool shape.
            if t.get("type") == "function" and isinstance(t.get("function"), dict):
                fn = t.get("function") or {}
                converted: Dict[str, Any] = {
                    "type": "function",
                    "name": fn.get("name"),
                    "description": fn.get("description"),
                    "strict": bool(fn.get("strict", False)),
                }
                if "parameters" in fn:
                    converted["input_schema"] = fn.get("parameters")
                out.append(converted)
                continue

            # Unknown tool shapes: forward as-is (best-effort).
            out.append(t)

        return out

    # ---- Main adaptation (always streaming completions-like) ----
    def adapt(self, req: Request) -> Dict[str, Any]:
        """Build requests.request kwargs for the Azure Responses API call.

        Maps inputs to the Responses schema and returns a dict suitable for
        requests.request(**kwargs).
        """
        # Reset per-request state
        self.adapter.inbound_model = None

        # Parse request body
        payload = req.get_json(silent=True, force=False)

        # Determine target model: prefer env AZURE_MODEL/AZURE_DEPLOYMENT
        inbound_model = payload.get("model") if isinstance(payload, dict) else None
        self.adapter.inbound_model = inbound_model

        settings = current_app.config

        upstream_headers = self._copy_request_headers_for_azure(
            req, api_key=settings["AZURE_API_KEY"]
        )

        # Map Chat/Completions to Responses (always streaming)
        responses_body: Dict[str, Any] = {"input": None, "instructions": None}
        if isinstance(payload, dict) and isinstance(payload.get("input"), list):
            responses_body["input"] = payload.get("input")
            if payload.get("instructions"):
                responses_body["instructions"] = payload.get("instructions")
        else:
            messages = payload.get("messages") or []
            responses_body = (
                self._messages_to_responses_input_and_instructions(messages)
                if isinstance(messages, list)
                else {"input": None, "instructions": None}
            )

        deployment, reasoning_effort = resolve_model_settings(inbound_model, settings)
        responses_body["model"] = deployment

        # Transform tools and tool choice
        responses_body["tools"] = self._transform_tools_for_responses(
            payload.get("tools", [])
        )
        responses_body["tool_choice"] = payload.get("tool_choice")

        responses_body["prompt_cache_key"] = payload.get("user")

        # Always streaming
        responses_body["stream"] = True

        reasoning = {}
        if isinstance(payload, dict) and isinstance(payload.get("reasoning"), dict):
            reasoning.update(payload.get("reasoning") or {})
        reasoning.setdefault("effort", reasoning_effort)
        responses_body["reasoning"] = reasoning

        # Concise is not supported by GPT-5,
        # but allowing it for now to be able to test it on other models
        if "summary" not in responses_body["reasoning"]:
            if settings["AZURE_SUMMARY_LEVEL"] in {"auto", "detailed", "concise"}:
                responses_body["reasoning"]["summary"] = settings["AZURE_SUMMARY_LEVEL"]
            else:
                raise ServiceConfigurationError(
                    "AZURE_SUMMARY_LEVEL must be either auto, detailed, or concise."
                    f"\n\nGot: {settings['AZURE_SUMMARY_LEVEL']}"
                )
        else:
            if responses_body["reasoning"]["summary"] not in {
                "auto",
                "detailed",
                "concise",
            }:
                raise ServiceConfigurationError(
                    "reasoning.summary must be either auto, detailed, or concise."
                    f"\n\nGot: {responses_body['reasoning']['summary']}"
                )

        # No need to pass verbosity if it's set to medium, as it's the model's default
        if isinstance(payload, dict) and isinstance(payload.get("text"), dict):
            responses_body["text"] = payload.get("text")
        elif settings["AZURE_VERBOSITY_LEVEL"] in {"low", "high"}:
            responses_body["text"] = {"verbosity": settings["AZURE_VERBOSITY_LEVEL"]}

        responses_body["store"] = False
        responses_body["stream_options"] = {"include_obfuscation": False}

        if isinstance(payload, dict) and payload.get("truncation"):
            responses_body["truncation"] = payload.get("truncation")
        elif settings["AZURE_TRUNCATION"] == "auto":
            responses_body["truncation"] = settings["AZURE_TRUNCATION"]

        request_kwargs: Dict[str, Any] = {
            "method": "POST",
            "url": settings["AZURE_RESPONSES_API_URL"],
            "headers": upstream_headers,
            "json": responses_body,
            "data": None,
            "stream": True,
            "timeout": (60, None),
        }
        return request_kwargs
