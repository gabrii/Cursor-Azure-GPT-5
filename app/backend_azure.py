"""Azure backend implementation and helpers for proxying to Azure Responses API."""

import json
import os
import random
import time
from typing import Any, Dict, Iterable, List, Optional

import requests
from flask import Request, Response
from loguru import logger
from rich.panel import Panel

from .common.logging import console, log_event
from .common.sse import chunks_to_sse, sse_to_events

SENSITIVE_HEADER_KEYS = {
    "authorization",
    "proxy-authorization",
    "x-api-key",
    "api-key",
    "api_key",
    "azure-openai-api-key",
    "x-azure-openai-key",
}


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


def should_redact() -> bool:
    """Return True if sensitive values should be redacted in logs."""
    return os.environ.get("LOG_REDACT", "true").strip().lower() not in {
        "0",
        "false",
        "no",
    }


def redact_value(value: str) -> str:
    """Mask a potentially sensitive value for safer logging."""
    if not value:
        return value
    if len(value) <= 8:
        return "***"
    return value[:4] + "…" + value[-4:]


def redact_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """Return a copy of headers with sensitive values redacted when enabled."""
    if not should_redact():
        return dict(headers)
    out: Dict[str, str] = {}
    for k, v in headers.items():
        if k.lower() in SENSITIVE_HEADER_KEYS:
            out[k] = redact_value(v)
        else:
            out[k] = v
    return out


def copy_request_headers_for_azure(src: Request, *, api_key: str) -> Dict[str, str]:
    """Copy request headers and set Azure api-key header for upstream call."""
    headers: Dict[str, str] = {k: v for k, v in src.headers.items()}
    headers.pop("Host", None)
    # Azure prefers api-key header
    headers.pop("Authorization", None)
    headers["api-key"] = api_key
    return headers


def filter_response_headers(
    headers: Dict[str, str], *, streaming: bool
) -> Dict[str, str]:
    """Filter hop-by-hop and incompatible headers for downstream responses."""
    out: Dict[str, str] = {}
    for k, v in headers.items():
        if k.lower() in HOP_BY_HOP_HEADERS:
            continue
        if streaming and k.lower() == "content-length":
            continue
        out[k] = v
    return out


def parse_json_body(req: Request, body: bytes) -> Optional[Any]:
    """Parse a request body into JSON using Flask helpers with fallbacks."""
    if not body:
        return None
    try:
        data = req.get_json(silent=True, force=False)
        if data is not None:
            return data
    except Exception:
        pass
    try:
        return json.loads(body.decode(req.charset or "utf-8", errors="replace"))
    except Exception:
        return None


def create_chat_completion_id() -> str:
    """Return a new pseudo-random chat completion id string."""
    return f"chatcmpl-{''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789', k=24))}"


def messages_to_responses_input_and_instructions(
    messages: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Map OpenAI-style messages to Azure Responses input and instructions."""
    instructions_parts: List[str] = []
    input_items: List[Dict[str, Any]] = []

    def content_to_text(c: Any) -> str:
        if c is None:
            return ""
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            parts: List[str] = []
            for it in c:
                if isinstance(it, dict):
                    if it.get("type") in {"text", "input_text"} and "text" in it:
                        parts.append(str(it.get("text", "")))
                    elif "content" in it and isinstance(it["content"], str):
                        parts.append(it["content"])
                else:
                    parts.append(str(it))
            return "\n".join([p for p in parts if p])
        try:
            return json.dumps(c, ensure_ascii=False)
        except Exception:
            return str(c)

    for m in messages:
        role = m.get("role")
        c = m.get("content")
        if role in {"system", "developer"}:
            text = content_to_text(c)
            if text:
                instructions_parts.append(text)
            continue
        # For user/assistant/tools as inputs
        if role == "tool":
            item = {
                "type": "function_call_output",
                "output": content_to_text(c),
                "status": "completed",
                "call_id": m.get("tool_call_id"),
            }
            input_items.append(item)
        else:
            text = content_to_text(c)
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
                    item = {
                        "type": "function_call",
                        "name": function.get("name"),
                        "arguments": function.get("arguments"),
                        "call_id": tool_call.get("id"),
                    }
                    input_items.append(item)

    instructions = "\n\n".join(instructions_parts) if instructions_parts else None
    return {"input": input_items if input_items else None, "instructions": instructions}


def clean_json_for_log(payload: Any) -> Any:
    """Return a simplified JSON object for logging purposes."""
    if isinstance(payload, dict):
        return {k: v for k, v in payload.items() if k not in {"messages", "tools"}}
    return payload


def transform_tools_for_responses(tools: Any) -> Any:
    """Transform OpenAI tools spec into Azure Responses tool definitions."""
    if not isinstance(tools, list):
        return tools
    out: List[Dict[str, Any]] = []
    for t in tools:
        if not isinstance(t, dict):
            out.append(t)
            continue
        ttype = t.get("type")
        if ttype == "function" and isinstance(t.get("function"), dict):
            f = t["function"]
            transformed: Dict[str, Any] = {"type": "function", "name": f.get("name")}
            if "description" in f:
                transformed["description"] = f["description"]
            if "parameters" in f:
                transformed["parameters"] = f["parameters"]
            out.append(transformed)
        else:
            out.append(t)
    return out


def transform_tool_choice(tool_choice: Any) -> Any:
    """Transform OpenAI-style tool_choice into Azure Responses equivalent."""
    if tool_choice in (None, "auto", "none"):
        return tool_choice
    if isinstance(tool_choice, dict):
        t = tool_choice.get("type")
        if t == "function":
            fn = tool_choice.get("function") or {}
            name = fn.get("name")
            if name:
                return {"type": "function", "name": name}
    return tool_choice


def wrap_data(data: str) -> bytes:
    """Encode a line of SSE data bytes (legacy helper)."""
    # Legacy helper retained for compatibility; unused in mapped streaming
    return b"data: " + data.encode("utf-8") + b"\n\n"


def build_completion_chunk(
    content: Optional[str] = None, chat_completion_id: Optional[str] = None
) -> Dict[str, Any]:
    """Build a Chat Completions delta chunk dict for text content."""
    obj = {
        "id": chat_completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "gpt-4.1-2025-04-14",
        "service_tier": "default",
        "system_fingerprint": "fp_daf5fcc80a",
        "choices": [
            {
                "index": 0,
                "delta": {
                    "role": "assistant",
                    "content": content,
                    "refusal": None,
                },
                "logprobs": None,
                "finish_reason": None,
            }
        ],
        "obfuscation": "sE7IOUI8k1",
    }
    console.print_json(data=obj)
    return obj


def build_function_call_start(
    name: str, arguments: str, chat_completion_id: str, call_id: str
) -> Dict[str, Any]:
    """Build the initial function call delta chunk with name and arguments."""
    obj = {
        "id": chat_completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "gpt-4.1-2025-04-14",
        "service_tier": "default",
        "system_fingerprint": "fp_daf5fcc80a",
        "choices": [
            {
                "index": 0,
                "delta": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": arguments},
                        }
                    ],
                },
                "logprobs": None,
                "finish_reason": None,
            }
        ],
        "obfuscation": "zoehyuKGQNd0V",
    }
    console.print_json(data=obj)
    return obj


def build_function_call_delta(delta: str, chat_completion_id: str) -> Dict[str, Any]:
    """Build a function call arguments delta chunk."""
    obj = {
        "id": chat_completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "gpt-4.1-2025-04-14",
        "service_tier": "default",
        "system_fingerprint": "fp_daf5fcc80a",
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [{"index": 0, "function": {"arguments": delta}}]
                },
                "logprobs": None,
                "finish_reason": None,
            }
        ],
        "obfuscation": "ECUilFglXQlUq",
    }
    console.print_json(data=obj)
    return obj


def build_finish_reason_chunk(
    finish_reason: str, chat_completion_id: str
) -> Dict[str, Any]:
    """Build the final chunk that carries the finish_reason value."""
    obj = {
        "id": chat_completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "gpt-4.1-2025-04-14",
        "service_tier": "default",
        "system_fingerprint": "fp_daf5fcc80a",
        "choices": [
            {"index": 0, "delta": {}, "logprobs": None, "finish_reason": finish_reason}
        ],
        "obfuscation": "",
    }
    console.print_json(data=obj)
    return obj


class Backend:
    """Abstract backend interface for forwarding requests."""

    def forward(self, req: Request) -> Response:
        """Forward a Flask request upstream and return a Flask Response."""
        raise NotImplementedError


class AzureBackend(Backend):
    """Concrete backend that proxies requests to Azure's Responses API."""

    def __init__(
        self, base_url: Optional[str] = None, session: Optional[requests.Session] = None
    ) -> None:
        """Initialize the backend with base URL and an HTTP session."""
        self.base_url = (
            base_url
            or os.environ.get("AZURE_BASE_URL")
            or "https://chrnt-swedencentral.openai.azure.com"
        ).rstrip("/")
        self.api_version = os.environ.get("AZURE_API_VERSION", "2025-04-01-preview")
        self.session = session or requests.Session()

    def _build_responses_url(self) -> str:
        """Return the Azure Responses API URL with version query parameter."""
        return f"{self.base_url}/openai/responses?api-version={self.api_version}"

    def forward(self, req: Request) -> Response:
        """Forward the Flask request to Azure and adapt the response back."""
        api_key = os.environ.get("AZURE_API_KEY")
        if not api_key:
            return Response("Missing AZURE_API_KEY", status=500, mimetype="text/plain")

        body = req.get_data(cache=True)
        payload = parse_json_body(req, body)
        method = req.method.upper()
        path = req.path or "/"

        # Determine target model: prefer payload.model, then env AZURE_MODEL/AZURE_DEPLOYMENT
        env_model = os.environ.get("AZURE_MODEL") or os.environ.get("AZURE_DEPLOYMENT")
        target_model = env_model
        if not target_model:
            return Response(
                "Missing model (set payload.model or AZURE_MODEL/AZURE_DEPLOYMENT)",
                status=400,
                mimetype="text/plain",
            )

        # Map OpenAI Chat/Completions to Responses
        is_completions_like = path.startswith("/v1/completions") or path.startswith(
            "/v1/chat/completions"
        )
        is_responses_like = path.startswith("/v1/responses")

        if method != "POST":
            return Response("Only POST supported for Azure backend", status=405)

        if not isinstance(payload, dict):
            payload = {}

        is_stream = bool(payload.get("stream"))

        upstream_headers = copy_request_headers_for_azure(req, api_key=api_key)

        if is_completions_like:
            # Transform into Responses request body
            messages = payload.get("messages") or []
            tools_in = payload.get("tools") or []
            tool_choice_in = payload.get("tool_choice")
            top_p = payload.get("top_p")
            max_tokens = payload.get("max_tokens") or payload.get("max_output_tokens")
            prompt_cache_key = payload.get("user") or payload.get("prompt_cache_key")

            mapped = (
                messages_to_responses_input_and_instructions(messages)
                if isinstance(messages, list)
                else {"input": None, "instructions": None}
            )

            responses_body: Dict[str, Any] = {}
            if mapped.get("instructions"):
                responses_body["instructions"] = mapped["instructions"]
            if mapped.get("input") is not None:
                responses_body["input"] = mapped["input"]
            if target_model:
                responses_body["model"] = target_model
            transformed_tools = transform_tools_for_responses(tools_in)
            if transformed_tools:
                responses_body["tools"] = transformed_tools
            mapped_tool_choice = transform_tool_choice(tool_choice_in)
            if mapped_tool_choice is not None:
                responses_body["tool_choice"] = mapped_tool_choice
            if top_p is not None:
                responses_body["top_p"] = top_p
            if max_tokens is not None:
                responses_body["max_output_tokens"] = max_tokens
            if prompt_cache_key is not None:
                responses_body["prompt_cache_key"] = prompt_cache_key
            if is_stream:
                responses_body["stream"] = True

            # Hardcoded extra params for quick testing
            responses_body["reasoning"] = {"effort": "high", "summary": "detailed"}
            responses_body["store"] = False
            responses_body["stream_options"] = {"include_obfuscation": False}

            # Bad, adding as temporary fix until we implement /models to potentially get the context size?
            responses_body["truncation"] = "auto"

            url = self._build_responses_url()

            logger.info(
                "Azure forward (mapped to Responses) → POST {} stream=\n{}",
                url,
                is_stream,
            )
            console.print(Panel.fit("Upstream Request Headers (Azure)"))
            console.print_json(data=redact_headers(upstream_headers))
            console.print(Panel.fit("Upstream Request JSON (mapped)"))
            console.print_json(
                data={k: v for k, v in responses_body.items() if k not in {"tools"}}
            )
            # if transformed_tools:
            #     console.print(Panel.fit(f"Tools ({len(transformed_tools)})"))
            #     console.print(transformed_tools)

            timeout_connect = float(os.environ.get("UPSTREAM_CONNECT_TIMEOUT", "10"))
            timeout_read = (
                None
                if is_stream
                else float(os.environ.get("UPSTREAM_READ_TIMEOUT", "6000"))
            )

            started = time.perf_counter()
            resp = self.session.request(
                method="POST",
                url=url,
                headers=upstream_headers,
                json=responses_body,
                stream=is_stream,
                timeout=(timeout_connect, timeout_read),
            )
            took_ms = (time.perf_counter() - started) * 1000

            console.print(
                Panel.fit(f"Upstream Response — {resp.status_code} in {took_ms:.1f} ms")
            )
            console.print_json(
                data=filter_response_headers(dict(resp.headers), streaming=is_stream)
            )
            if resp.status_code >= 400:
                try:
                    err_json = resp.json()
                    console.print(
                        Panel.fit(f"Upstream Error JSON ({resp.status_code})")
                    )
                    console.print_json(data=err_json)
                except Exception:
                    try:
                        console.print(resp.content)
                    except:
                        try:
                            resp.raise_for_status()
                        except Exception:
                            console.print_exception()

            if is_stream:

                def generate() -> Iterable[bytes]:
                    """SSE generator mapping Azure events into OpenAI chunk JSON."""
                    chat_completion_id = create_chat_completion_id()
                    # Becomes true when the model starts reasoning, and outputs <think> on the first reasoning token
                    started_thinking = False

                    # Becomes true when the model outputs first reasonign token,
                    # and false when the model outputs the first non-reasoning token and we output </think>
                    thinking = False

                    # Becomes true when any function call is made, in order to set the corresponding finish_reason
                    called_function = False

                    def gen_dicts() -> Iterable[Dict[str, Any]]:
                        """Yield downstream chunk dicts for each relevant SSE event."""
                        nonlocal started_thinking, thinking, called_function
                        try:
                            for ev in sse_to_events(resp.iter_content(chunk_size=8192)):
                                if ev.is_done:
                                    logger.info("Azure stream: [DONE]")
                                    continue
                                obj = ev.json
                                log_event(ev)

                                if (
                                    ev.event == "response.output_item.added"
                                    and obj is not None
                                ):
                                    item_type = obj.get("item", {}).get("type")
                                    if item_type == "reasoning":
                                        started_thinking = True
                                    elif item_type == "function_call":
                                        if thinking:
                                            yield build_completion_chunk(
                                                "</think>\n\n", chat_completion_id
                                            )
                                            thinking = False
                                        name = obj.get("item", {}).get("name")
                                        arguments = obj.get("item", {}).get("arguments")
                                        call_id = obj.get("item", {}).get("call_id")
                                        yield build_function_call_start(
                                            name, arguments, chat_completion_id, call_id
                                        )
                                        called_function = True
                                elif (
                                    ev.event == "response.function_call_arguments.delta"
                                    and obj is not None
                                ):
                                    if thinking:
                                        yield build_completion_chunk(
                                            "</think>\n\n", chat_completion_id
                                        )
                                        thinking = False
                                    delta = obj.get("delta", "")
                                    yield build_function_call_delta(
                                        delta, chat_completion_id
                                    )
                                elif (
                                    ev.event == "response.output_item.done"
                                    and obj is not None
                                ):
                                    item_type = obj.get("item", {}).get("type")
                                    # if item_type == "reasoning":
                                    #     yield create_completion_chunk("</think>")
                                elif (
                                    ev.event == "response.reasoning_summary_text.delta"
                                    and obj is not None
                                ):
                                    if started_thinking:
                                        yield build_completion_chunk(
                                            "<think>", chat_completion_id
                                        )
                                        thinking = True
                                        started_thinking = False
                                    yield build_completion_chunk(
                                        obj.get("delta", ""), chat_completion_id
                                    )
                                elif ev.event == "response.reasoning_summary_text.done":
                                    yield build_completion_chunk(
                                        "\n\n", chat_completion_id
                                    )
                                elif (
                                    ev.event == "response.output_text.delta"
                                    and obj is not None
                                ):
                                    if thinking:
                                        yield build_completion_chunk(
                                            "</think>\n\n", chat_completion_id
                                        )
                                        thinking = False
                                    yield build_completion_chunk(
                                        obj.get("delta", ""), chat_completion_id
                                    )
                        finally:
                            # Emit finish reason dict at the end of stream
                            if called_function:
                                yield build_finish_reason_chunk(
                                    "tool_calls", chat_completion_id
                                )
                            else:
                                yield build_finish_reason_chunk(
                                    "stop", chat_completion_id
                                )

                    try:
                        # Wrap the dict generator with SSE encoder (auto-appends [DONE])
                        yield from chunks_to_sse(gen_dicts())
                    finally:
                        try:
                            resp.close()
                        except Exception:
                            pass

                headers = filter_response_headers(dict(resp.headers), streaming=True)
                # Ensure SSE headers for downstream consumer
                headers["Content-Type"] = "text/event-stream; charset=utf-8"
                headers.pop("Content-Length", None)
                headers["Cache-Control"] = "no-cache"
                headers["Connection"] = "keep-alive"
                headers["X-Accel-Buffering"] = "no"
                return Response(generate(), status=resp.status_code, headers=headers)

            content = resp.content or b""
            # Log JSON error body if present
            if resp.status_code >= 400:
                try:
                    err_json = resp.json()
                    console.print(
                        Panel.fit(f"Upstream Error JSON ({resp.status_code})")
                    )
                    console.print_json(data=err_json)
                except Exception:
                    pass
            headers = filter_response_headers(dict(resp.headers), streaming=False)
            return Response(content, status=resp.status_code, headers=headers)

        # For /v1/responses directly, send to Azure /openai/v1/responses
        if is_responses_like:
            url = self._build_responses_url()
            is_stream = bool(payload.get("stream"))
            logger.info(
                "Azure forward (direct Responses) → POST {} stream=\n{}", url, is_stream
            )
            console.print(Panel.fit("Upstream Request Headers (Azure)"))
            console.print_json(data=redact_headers(upstream_headers))
            console.print(Panel.fit("Upstream Request JSON (clean)"))
            console.print(clean_json_for_log(payload))

            timeout_connect = float(os.environ.get("UPSTREAM_CONNECT_TIMEOUT", "10"))
            timeout_read = (
                None
                if is_stream
                else float(os.environ.get("UPSTREAM_READ_TIMEOUT", "60"))
            )

            resp = self.session.request(
                method="POST",
                url=url,
                headers=upstream_headers,
                json=payload,
                stream=is_stream,
                timeout=(timeout_connect, timeout_read),
            )

            if is_stream:

                def generate() -> Iterable[bytes]:
                    """Pass through upstream SSE bytes, ensuring cleanup on close."""
                    try:
                        for chunk in resp.iter_content(chunk_size=8192):
                            if not chunk:
                                continue
                            yield chunk
                    finally:
                        try:
                            resp.close()
                        except Exception:
                            pass

                headers = filter_response_headers(dict(resp.headers), streaming=True)
                headers["Content-Type"] = "text/event-stream; charset=utf-8"
                headers.pop("Content-Length", None)
                headers["Cache-Control"] = "no-cache"
                headers["Connection"] = "keep-alive"
                headers["X-Accel-Buffering"] = "no"
                return Response(generate(), status=resp.status_code, headers=headers)

            content = resp.content or b""
            headers = filter_response_headers(dict(resp.headers), streaming=False)
            return Response(content, status=resp.status_code, headers=headers)

        # Otherwise, not yet implemented for Azure
        return Response(
            "Azure backend: unsupported path for now", status=501, mimetype="text/plain"
        )
