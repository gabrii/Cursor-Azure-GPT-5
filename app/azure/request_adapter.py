"""Request adaptation helpers for Azure Responses API.

This module defines RequestAdapter, which transforms incoming OpenAI-style
requests into Azure Responses API request parameters.
"""

from __future__ import annotations

from typing import Any, Dict, List

from flask import Request, current_app

from ..exceptions import CursorConfigurationError, ServiceConfigurationError


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
    def _content_to_text(self, content: Any) -> str:
        """Convert message content (string or list of parts) to a string for Azure."""
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        parts.append(part.get("text", ""))
                    elif part.get("type") == "image_url":
                        parts.append("[image]")
                    else:
                        parts.append(f"[{part.get('type', 'unknown')}]")
                else:
                    parts.append(str(part))
            return "\n".join(parts) if parts else ""
        return str(content)

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
            content = m.get("content")
            if role in {"system", "developer"}:
                instructions_parts.append(self._content_to_text(content))
                continue
            # For user/assistant/tools as inputs
            if role == "tool":
                call_id = m.get("tool_call_id")
                item = {
                    "type": "function_call_output",
                    "output": self._content_to_text(content),
                    "status": "completed",
                    "call_id": call_id,
                }
                input_items.append(item)
            else:
                text_content = self._content_to_text(content)
                item = {
                    "role": role or "user",
                    "content": [
                        {
                            "type": "input_text" if role == "user" else "output_text",
                            "text": text_content,
                        },
                    ],
                }
                input_items.append(item)

                if tool_calls := m.get("tool_calls"):
                    for tool_call in tool_calls or []:
                        if not isinstance(tool_call, dict):
                            continue
                        function = tool_call.get("function") or {}
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
        out: List[Dict[str, Any]] = []
        if not isinstance(tools, list):
            current_app.logger.debug(
                "Skipping tool transformation because tools payload is not a list: %r",
                tools,
            )
            return out

        # Debug: log the shape of first tool to understand what Cursor sends
        if tools:
            sample = tools[0] if isinstance(tools[0], dict) else {}
            from ..common.logging import console

            console.print(
                f"[bold yellow]TOOL_DEBUG:[/bold yellow] count={len(tools)}, "
                f"first_keys={list(sample.keys())[:10]}, type={sample.get('type')}, "
                f"has_function={'function' in sample}, has_name={'name' in sample}"
            )

        for tool in tools:
            if not isinstance(tool, dict):
                continue
            function = tool.get("function")
            if not function:
                # Tool might already be in Responses API format (has "name" at top level)
                if tool.get("name"):
                    out.append(tool)
                else:
                    from ..common.logging import console

                    console.print(
                        f"[bold red]TOOL_SKIPPED:[/bold red] tool has no 'function' and no 'name'. "
                        f"keys={list(tool.keys())[:10]}"
                    )
                continue
            transformed: Dict[str, Any] = {
                "type": "function",
                "name": function.get("name"),
                "description": function.get("description"),
                "parameters": function.get("parameters"),
                "strict": False,
            }
            out.append(transformed)

        from ..common.logging import console

        console.print(
            f"[bold yellow]TOOL_TRANSFORM:[/bold yellow] {len(tools)} tools in → {len(out)} tools out"
        )
        if out:
            console.print(
                f"[bold yellow]TOOL_TRANSFORM:[/bold yellow] first out name={out[0].get('name')}"
            )
        return out

    def _resolve_model_and_reasoning(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve the Azure deployment and reasoning settings for this request."""
        settings = current_app.config
        inbound_model = payload.get("model")

        model_map = {
            # gpt-5.4 variants
            "gpt-5.4-none": ("gpt-5.4", "none"),
            "gpt-5.4-low": ("gpt-5.4", "low"),
            "gpt-5.4-medium": ("gpt-5.4", "medium"),
            "gpt-5.4-high": ("gpt-5.4", "high"),
            "gpt-5.4-xhigh": ("gpt-5.4", "xhigh"),
            # bare names now rely on Cursor's native reasoning field
            "gpt-5.4": ("gpt-5.4", None),
            # gpt-5.4-mini variants
            "gpt-5.4-mini-none": ("gpt-5.4-mini", "none"),
            "gpt-5.4-mini-low": ("gpt-5.4-mini", "low"),
            "gpt-5.4-mini-medium": ("gpt-5.4-mini", "medium"),
            "gpt-5.4-mini-high": ("gpt-5.4-mini", "high"),
            "gpt-5.4-mini-xhigh": ("gpt-5.4-mini", "xhigh"),
            # bare names now rely on Cursor's native reasoning field
            "gpt-5.4-mini": ("gpt-5.4-mini", None),
            # Legacy names → use env AZURE_DEPLOYMENT for backwards compatibility
            "gpt-high": (settings["AZURE_DEPLOYMENT"], "high"),
            "gpt-medium": (settings["AZURE_DEPLOYMENT"], "medium"),
            "gpt-low": (settings["AZURE_DEPLOYMENT"], "low"),
            "gpt-minimal": (settings["AZURE_DEPLOYMENT"], "minimal"),
        }

        model_key = (inbound_model or "").lower()
        if model_key not in model_map:
            raise CursorConfigurationError(
                "Model name must be one of:\n"
                "  gpt-5.4, gpt-5.4-none, gpt-5.4-low, gpt-5.4-medium, gpt-5.4-high, gpt-5.4-xhigh\n"
                "  gpt-5.4-mini, gpt-5.4-mini-none, gpt-5.4-mini-low, "
                "gpt-5.4-mini-medium, gpt-5.4-mini-high, gpt-5.4-mini-xhigh\n"
                "  gpt-high, gpt-medium, gpt-low, gpt-minimal\n"
                f"\nGot: {inbound_model}"
            )

        azure_deployment, model_effort = model_map[model_key]
        inbound_reasoning = (
            payload.get("reasoning") if isinstance(payload, dict) else None
        )
        inbound_effort = (
            inbound_reasoning.get("effort")
            if isinstance(inbound_reasoning, dict)
            else None
        )
        inbound_summary = (
            inbound_reasoning.get("summary")
            if isinstance(inbound_reasoning, dict)
            else None
        )

        if inbound_effort is not None:
            reasoning_effort = inbound_effort
            reasoning_source = "native_request"
        elif model_effort is not None:
            reasoning_effort = model_effort
            reasoning_source = "legacy_model_suffix"
        else:
            raise CursorConfigurationError(
                "Cursor must send reasoning.effort when using bare model names like "
                f"{inbound_model}."
            )

        return {
            "azure_deployment": azure_deployment,
            "reasoning_effort": reasoning_effort,
            "reasoning_source": reasoning_source,
            "inbound_reasoning_present": isinstance(inbound_reasoning, dict),
            "inbound_summary": inbound_summary,
        }

    # ---- Main adaptation (always streaming completions-like) ----
    def adapt(self, req: Request) -> Dict[str, Any]:
        """Build requests.request kwargs for the Azure Responses API call.

        Maps inputs to the Responses schema and returns a dict suitable for
        requests.request(**kwargs).
        """
        # Reset per-request state
        self.adapter.inbound_model = None

        # Parse request body (Cursor sometimes sends malformed payloads)
        payload = req.get_json(silent=True, force=False) or {}

        # Determine target model
        inbound_model = payload.get("model") if isinstance(payload, dict) else None
        self.adapter.inbound_model = inbound_model

        settings = current_app.config

        upstream_headers = self._copy_request_headers_for_azure(
            req, api_key=settings["AZURE_API_KEY"]
        )

        # Map Chat/Completions to Responses (always streaming)
        # Cursor may send either:
        #   - Chat Completions format: {"messages": [...]}
        #   - Responses API format:    {"input": [...], "instructions": "..."}
        messages = payload.get("messages")
        raw_input = payload.get("input")

        if messages and isinstance(messages, list):
            # Standard Chat Completions → convert to Responses format
            responses_body = self._messages_to_responses_input_and_instructions(
                messages
            )
        elif raw_input is not None:
            # Already in Responses API format — pass through
            responses_body = {
                "input": raw_input,
                "instructions": payload.get("instructions"),
            }
        else:
            responses_body = {"input": "", "instructions": None}

        resolved_reasoning = self._resolve_model_and_reasoning(payload)
        azure_deployment = resolved_reasoning["azure_deployment"]
        reasoning_effort = resolved_reasoning["reasoning_effort"]
        reasoning_source = resolved_reasoning["reasoning_source"]
        inbound_reasoning_present = resolved_reasoning["inbound_reasoning_present"]
        inbound_summary = resolved_reasoning["inbound_summary"]

        from ..common.logging import console

        console.print(
            "[bold cyan]REQUEST:[/bold cyan] "
            f"model={azure_deployment} "
            f"inbound_model={inbound_model} "
            f"inbound_reasoning={inbound_reasoning_present} "
            f"effort={reasoning_effort} "
            f"source={reasoning_source}"
        )

        responses_body["model"] = azure_deployment

        # Transform tools and tool choice
        responses_body["tools"] = self._transform_tools_for_responses(
            payload.get("tools", [])
        )
        responses_body["tool_choice"] = payload.get("tool_choice")

        responses_body["prompt_cache_key"] = payload.get("user")

        # Always streaming
        responses_body["stream"] = True

        responses_body["reasoning"] = {
            "effort": reasoning_effort,
        }

        if inbound_summary is not None:
            responses_body["reasoning"]["summary"] = inbound_summary
        # Concise is not supported by GPT-5,
        # but allowing it for now to be able to test it on other models
        elif settings["AZURE_SUMMARY_LEVEL"] in {"auto", "detailed", "concise"}:
            responses_body["reasoning"]["summary"] = settings["AZURE_SUMMARY_LEVEL"]
        else:
            raise ServiceConfigurationError(
                "AZURE_SUMMARY_LEVEL must be either auto, detailed, or concise."
                f"\n\nGot: {settings['AZURE_SUMMARY_LEVEL']}"
            )

        # No need to pass verbosity if it's set to medium, as it's the model's default
        if settings["AZURE_VERBOSITY_LEVEL"] in {"low", "high"}:
            responses_body["text"] = {"verbosity": settings["AZURE_VERBOSITY_LEVEL"]}

        responses_body["store"] = False
        responses_body["stream_options"] = {"include_obfuscation": False}

        if settings["AZURE_TRUNCATION"] == "auto":
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
