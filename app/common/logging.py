import json
import os
import time
import uuid
from typing import Any, Dict, List

from flask import Request
from rich.console import Console
from rich.panel import Panel

from .sse import SSEEvent

# Global console instance for consistent logging across modules
console = Console()


# --- Request logging helpers ---


def should_redact() -> bool:
    # Set LOG_REDACT=false to disable redaction (default True)
    return os.environ.get("LOG_REDACT", "true").strip().lower() not in {
        "0",
        "false",
        "no",
    }


def redact_value(value: str) -> str:
    if not value:
        return value
    if len(value) <= 8:
        return "***"
    return value[:4] + "…" + value[-4:]


def redact_headers(headers: Dict[str, str]) -> Dict[str, str]:
    if not should_redact():
        return dict(headers)
    redacted: Dict[str, str] = {}
    sensitive = {
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "api-key",
        "api_key",
        "x-azure-openai-key",
        "azure-openai-key",
    }
    for k, v in headers.items():
        if k.lower() in sensitive:
            redacted[k] = redact_value(v)
        else:
            # Heuristic: mask common bearer/api-key looking values
            if isinstance(v, str) and (
                v.startswith("Bearer ") or v.startswith("sk-") or "api_key" in k.lower()
            ):
                redacted[k] = redact_value(v)
            else:
                redacted[k] = v
    return redacted


def multidict_to_dict(md) -> Dict[str, List[str]]:
    try:
        return {k: list(vs) for k, vs in md.lists()}
    except Exception:
        # Fallback for objects without .lists()
        return {k: [md.get(k)] for k in md.keys()}


def files_summary(req: Request) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for name, storage in req.files.items():
        try:
            items.append(
                {
                    "field": name,
                    "filename": storage.filename,
                    "content_type": storage.content_type,
                }
            )
        except Exception:
            items.append(
                {
                    "field": name,
                    "filename": "<unavailable>",
                    "content_type": "<unknown>",
                }
            )
    return items


def _capture_request_details(req: Request, request_id: str) -> Dict[str, Any]:
    # Note: access request inside request context
    hdrs = {k: v for k, v in req.headers.items()}
    redacted_headers = redact_headers(hdrs)

    details: Dict[str, Any] = {
        "id": request_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
        "remote_addr": (req.headers.get("X-Forwarded-For") or req.remote_addr or ""),
        "method": req.method,
        "scheme": req.scheme,
        "path": "/" + (req.view_args.get("path", "") if req.view_args else ""),
        "full_path": req.full_path,  # includes trailing ?
        "url": req.url,
        "route_args": dict(req.view_args or {}),
        "query_args": multidict_to_dict(req.args),
        "form": multidict_to_dict(req.form),
        "json": req.get_json(silent=True),
        "files": files_summary(req),
        "cookies": req.cookies.to_dict() if req.cookies else {},
        "headers": redacted_headers,
        "user_agent": str(req.user_agent) if req.user_agent else "",
    }
    return details


def log_request(req: Request) -> str:
    """
    Pretty-print a Flask request using Rich. Returns the generated request id.
    """
    request_id = uuid.uuid4().hex[:8]
    details = _capture_request_details(req, request_id)

    method = details.get("method")
    path = details.get("path") or "/"
    rid = details.get("id")

    # Rich pretty print of the full request details
    console.rule(f"[bold]Request #{rid}[/bold] — {method} {path}")
    console.print(Panel.fit("Headers"))
    console.print(details.get("headers"))
    console.print(Panel.fit("Args / Form / JSON"))
    json_payload = details.get("json")
    cleaned_json = json_payload
    if isinstance(json_payload, dict):
        # Remove verbose fields to log them separately
        cleaned_json = {
            k: v
            for k, v in json_payload.items()
            if k
            not in {
                "tools",
            }
        }
    console.print_json(
        data={
            "query_args": details.get("query_args"),
            "form": details.get("form"),
            "json": cleaned_json,
        }
    )

    # Separate section for chat messages (role + content)
    messages = []
    if isinstance(json_payload, dict):
        maybe_messages = json_payload.get("messages")
        if isinstance(maybe_messages, list):
            messages = maybe_messages

    if messages:
        console.rule(f"Messages ({len(messages)})")

        def render_content(content: Any) -> str:
            # Show content with actual newlines
            if content is None:
                return ""
            if isinstance(content, bytes):
                try:
                    return content.decode("utf-8", errors="replace")
                except Exception:
                    return str(content)
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts: List[str] = []
                for it in content:
                    if isinstance(it, dict):
                        t = it.get("type")
                        if t == "text" and "text" in it:
                            parts.append(str(it.get("text", "")))
                        elif "content" in it and isinstance(it["content"], str):
                            parts.append(it["content"])
                        else:
                            parts.append(json.dumps(it, ensure_ascii=False, indent=2))
                    else:
                        parts.append(str(it))
                return "\n".join(p for p in parts if p is not None)
            # Fallback: pretty JSON
            try:
                return json.dumps(content, ensure_ascii=False, indent=2)
            except Exception:
                return str(content)

        for idx, msg in enumerate(messages, start=1):
            role = ""
            content_val: Any = ""
            name = None
            if isinstance(msg, dict):
                role = str(msg.get("role", ""))
                content_val = msg.get("content", "")
                name = msg.get("name")
            title = (
                f"Message {idx}: {role}"
                if not name
                else f"Message {idx}: {role} ({name})"
            )
            console.rule(title)
            console.print(render_content(content_val), markup=False)

    return request_id


# --- SSE logging helpers ---


def _clean_payload(obj: Any) -> Any:
    """
    Default cleaning to reduce noisy fields in logs.
    - If obj is a dict, remove top-level 'tools'
    - If it contains a nested 'response' dict, also remove its 'tools'
    Returns a shallow-cleaned copy when applicable; otherwise returns the input unchanged.
    """
    if not isinstance(obj, dict):
        return obj
    # Shallow copy top-level
    cleaned = {k: v for k, v in obj.items()}
    if "tools" in cleaned:
        cleaned = {k: v for k, v in cleaned.items() if k != "tools"}
    resp = cleaned.get("response")
    if isinstance(resp, dict) and "tools" in resp:
        # Shallow copy nested response to drop tools
        new_resp = {k: v for k, v in resp.items() if k != "tools"}
        cleaned = {**cleaned, "response": new_resp}
    return cleaned


def log_event(ev: SSEEvent) -> None:
    """
    Pretty-print one SSE event using Rich.
    - Title reflects whether the event had an 'event' name and its index
    - If payload parses as JSON (ev.json), it is cleaned and printed as JSON; otherwise raw text is printed
    """
    obj = ev.json
    if obj is not None:
        title = (
            f"SSE JSON #{ev.index}" if not ev.event else f"SSE {ev.event} #{ev.index}"
        )
        console.print(Panel.fit(title))
        console.print_json(data=_clean_payload(obj))
    else:
        title = f"SSE data #{ev.index}"
        if ev.event:
            title = f"SSE {ev.event} #{ev.index}"
        console.print(Panel.fit(title))
        console.print(ev.data)
