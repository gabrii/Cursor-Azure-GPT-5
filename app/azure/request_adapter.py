"""Request adaptation helpers for Azure Responses API.

This module defines RequestAdapter, which transforms incoming OpenAI-style
requests into Azure Responses API request parameters.
"""

from __future__ import annotations

from typing import Any, Dict, List

from flask import Request, current_app


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

        for m in messages:
            role = m.get("role")
            c = m.get("content")
            if role in {"system", "developer"}:
                text = c
                if text:
                    instructions_parts.append(text)
                continue
            # For user/assistant/tools as inputs
            if role == "tool":
                call_id = m.get("tool_call_id")

                item = {
                    "type": "function_call_output",
                    "output": c,
                    "status": "completed",
                    "call_id": call_id,
                }
                input_items.append(item)
            else:
                text = c
                item = {
                    "role": role or "user",
                    "content": [
                        {
                            "type": "input_text" if role == "user" else "output_text",
                            "text": text,
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
            "input": input_items if input_items else None,
            "instructions": instructions,
        }

    def _transform_tools_for_responses(self, tools: Any) -> Any:
        out: List[Dict[str, Any]] = []
        for t in tools:
            ttype = t.get("type")
            if ttype == "function" and isinstance(t.get("function"), dict):
                f = t["function"]
                transformed: Dict[str, Any] = {
                    "type": "function",
                    "name": f.get("name"),
                }
                if "description" in f:
                    transformed["description"] = f["description"]
                if "parameters" in f:
                    transformed["parameters"] = f["parameters"]
                transformed["strict"] = False
                out.append(transformed)
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
        messages = payload.get("messages") or []
        tools_in = payload.get("tools") or []
        tool_choice_in = payload.get("tool_choice")
        prompt_cache_key = payload.get("user") or payload.get("prompt_cache_key")

        mapped = (
            self._messages_to_responses_input_and_instructions(messages)
            if isinstance(messages, list)
            else {"input": None, "instructions": None}
        )

        responses_body: Dict[str, Any] = {}
        if mapped.get("instructions"):
            responses_body["instructions"] = mapped["instructions"]
        if mapped.get("input") is not None:
            responses_body["input"] = mapped["input"]
        responses_body["model"] = settings["AZURE_DEPLOYMENT"]

        # Transform tools and tool choice
        if tools_in:
            responses_body["tools"] = self._transform_tools_for_responses(tools_in)
        if tool_choice_in is not None:
            responses_body["tool_choice"] = tool_choice_in

        if prompt_cache_key is not None:
            responses_body["prompt_cache_key"] = prompt_cache_key

        # Always streaming
        responses_body["stream"] = True

        reasoning_effort = inbound_model.replace("gpt-", "").lower()
        if reasoning_effort not in {"high", "medium", "low", "minimal"}:
            raise ValueError(
                "Model name must be either gpt-high, gpt-medium, gpt-low, or gpt-minimal"
            )

        responses_body["reasoning"] = {
            "effort": reasoning_effort,
        }

        # Concise is not supported by GPT-5,
        # but allowing it for now to be able to test it on other models
        if settings["AZURE_SUMMARY_LEVEL"] in {"auto", "detailed", "concise"}:
            responses_body["reasoning"]["summary"] = settings["AZURE_SUMMARY_LEVEL"]

        responses_body["store"] = False
        responses_body["stream_options"] = {"include_obfuscation": False}
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
