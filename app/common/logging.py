"""Utilities for structured, pretty logging of requests and SSE events."""

import json
import os
import re
import time
import uuid
from typing import Any, Dict, List

from flask import Request
from rich import box
from rich.console import Console, Group
from rich.json import JSON
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table

# Global console instance for consistent logging across modules
console = Console()
ROLE_COLORS = {
    "tool": "magenta",
    "system": "yellow",
    "user": "cyan",
    "assistant": "light_green",
}


def should_redact() -> bool:
    """Return True if sensitive values should be redacted in logs."""
    # Set LOG_REDACT=false to disable redaction (default True)
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
        return "..."
    return value[:4] + "…" + value[-4:]


def redact_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """Return a copy of headers with sensitive values redacted when enabled."""
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
            redacted[k] = v
    return redacted


def multidict_to_dict(md) -> Dict[str, List[str]]:
    """Convert a werkzeug MultiDict-like object to a plain dict of lists."""
    return {k: list(vs) for k, vs in md.lists()}


def _capture_request_details(req: Request, request_id: str) -> Dict[str, Any]:
    """Collect a structured snapshot of request information for logging."""
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
        "cookies": req.cookies.to_dict() if req.cookies else {},
        "headers": redacted_headers,
        "user_agent": str(req.user_agent) if req.user_agent else "",
    }
    return details


def escape_tags(text: str) -> str:
    """Escapes xml-like tags in text so that they are visible when rendered as Markdown."""
    return re.sub(
        "(<[^<\n]+?)(>)", "\\1>`\n", re.sub("(<)([^>\n]+?>)", "\n`<\\2", text)
    ).replace(">`\n\n\n`<", ">`\n\n`<")


def log_request(req: Request) -> str:
    """Pretty-print a Flask request using Rich and return the request id."""
    request_id = uuid.uuid4().hex[:8]
    details = _capture_request_details(req, request_id)

    method = details.get("method")
    path = details.get("path") or "/"
    rid = details.get("id")

    # Rich pretty print of the full request details
    console.rule(f"[bold]Request #{rid}[/bold] — {method} {path}")
    json_payload = details.get("json")

    # Remove verbose fields to log them separately
    cleaned_json = {
        k: v if k not in {"tools", "messages"} else "Pretty-printed below ↓"
        for k, v in json_payload.items()
    }
    console.print_json(
        data=cleaned_json,
        indent=None,
    )

    messages = json_payload.get("messages", [])
    tools = json_payload.get("tools", [])

    for idx, tool in enumerate(tools, start=1):
        table = Table(
            caption="[italic]Required fields are marked with *[/italic]",
            pad_edge=False,
            box=box.SIMPLE,
            leading=2,
        )

        table.add_column("Name", justify="right", style="cyan", no_wrap=True)
        table.add_column("Description", style="white")

        for tool in tools:
            function = tool.get("function")
            required = function.get("parameters").get("required")

            params_table = Table(
                show_header=False,
                show_edge=True,
                show_lines=True,
                title="Parameters",
                title_justify="left",
                expand=True,
                leading=3,
            )
            params_table.add_column("Name", justify="right", no_wrap=True, style="cyan")
            params_table.add_column("Description", style="white")
            for param_name, param_value in (
                function.get("parameters").get("properties").items()
            ):
                param_type = param_value.get("type")
                if param_type == "array":
                    param_type += f"({param_value.get('items').get('type')})"
                if param_name in required:
                    param_type = f"[bold]*{param_type}[/bold]"
                param_type = f"[magenta]{param_type}[/magenta]"
                param_name = f"{param_name}"
                params_table.add_row(
                    Group(param_name, param_type),
                    f"{param_value.get("description")}",
                )
            table.add_row(
                f"{function.get('name')}",
                Group(
                    Markdown(escape_tags(function.get("description"))),
                    params_table,
                ),
            )

        console.print(
            Panel(
                table,
                title=f"[italic]{0}/{len(messages)}[/italic] [bold]<tools>[/bold]",
                title_align="left",
                subtitle="[bold]</tools>[/bold]",
                subtitle_align="right",
                border_style=ROLE_COLORS["tool"],
            )
        )

    for idx, msg in enumerate(messages, start=1):
        role = str(msg.get("role", ""))
        content_val = msg.get("content", "")
        name = msg.get("name")
        tool_call_id = msg.get("tool_call_id")
        message_title = (
            f"[italic]{idx}/{len(messages)}[/italic] [bold]<{role}>[/bold]"
            if not name
            else f"[italic]{idx}/{len(messages)}[/italic] [bold]<{role} name={name} id={tool_call_id}>[/bold]"
        )
        message_elements = []
        message_elements.append(
            Padding(
                Markdown(
                    escape_tags(content_val),
                ),
                (1, 0),
            )
        )
        tool_calls = msg.get("tool_calls", [])
        for tool_call in tool_calls:
            function = tool_call.get("function", {})
            arguments = function.get("arguments")
            tool_elements = []
            tool_title = f"[bold]<tool_call id={tool_call.get('id')}>[/bold]"
            tool_elements.append(
                f"[bold][magenta]{function.get('name')}[/magenta] [blue]([/blue][/bold]",
            )
            try:
                tool_elements.append(Padding(JSON(arguments), (0, 4)))
            except json.JSONDecodeError:
                tool_elements.append(
                    Padding("[red]Invalid JSON generated by the model:[/red]", (0, 4))
                )
                tool_elements.append(arguments)
            tool_elements.append("[bold][blue])[/blue][/bold]")
            message_elements.append(
                Panel(
                    Group(*tool_elements),
                    title=tool_title,
                    border_style=ROLE_COLORS["tool"],
                )
            )
        message_style = ROLE_COLORS.get(role, "red")
        message_subtitle = message_title[message_title.find("<") :].replace("<", "</")
        message_subtitle = (
            "[bold]"
            + message_subtitle[
                : (
                    message_subtitle.find(" ")
                    if " " in message_subtitle
                    else message_subtitle.find(">")
                )
            ]
            + ">[/bold]"
        )
        console.print(
            Panel(
                Group(*message_elements),
                title=message_title,
                title_align="left",
                subtitle=message_subtitle,
                subtitle_align="right",
                border_style=message_style,
            )
        )

    return request_id
