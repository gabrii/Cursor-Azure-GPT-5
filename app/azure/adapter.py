"""Azure adapter orchestrating request/response transformations."""

from __future__ import annotations

import json
import re
from typing import Optional

import requests
from flask import Request, Response

from ..common.logging import console
from ..common.recording import record_payload

# Local adapters
from .request_adapter import RequestAdapter
from .response_adapter import ResponseAdapter


class AzureAdapter:
    """Orchestrate forwarding of a Flask Request to Azure's Responses API.

    Provides a Completions-compatible interface to the caller by composing a
    RequestAdapter (pre-request transformations) and a ResponseAdapter
    (post-request transformations). The adapters receive a reference to this
    instance for shared per-request state (models).
    """

    # Per-request state (streaming completions only)
    inbound_model: Optional[str] = None

    def __init__(self) -> None:
        """Initialize child adapters and shared state references."""
        # Composition: child adapters get a reference to this orchestrator
        self.request_adapter = RequestAdapter(self)
        self.response_adapter = ResponseAdapter(self)

    # Public API
    def forward(self, req: Request) -> Response:
        """Forward the Flask request upstream and adapt the response back.

        High-level flow:
        1) RequestAdapter builds the upstream request kwargs and stores state
           on this adapter (models).
        2) Perform the upstream HTTP call using a short-lived requests call.
        3) ResponseAdapter converts the upstream response into a Flask Response.
        """
        request_kwargs = self.request_adapter.adapt(req)

        record_payload(request_kwargs.get("json", {}), "upstream_request")

        # Perform upstream request with kwargs directly (no long-lived session)
        resp = requests.request(**request_kwargs)
        if resp.status_code != 200:
            return self._handle_azure_error(resp, request_kwargs)

        return self.response_adapter.adapt(resp)

    def _handle_azure_error(self, resp: Response, request_kwargs) -> Response:

        try:
            resp_content = resp.json()
        except ValueError:
            resp_content = resp.text

        body = request_kwargs.get("json", {})
        if "instructions" in body:
            body["instructions"] = body["instructions"][:7] + "..."

        if "tools" in body:
            body["tools"] = f"...redacted {len(body['tools'])} tools..."

        if "input" in body:
            body["input"] = f"...redacted {len(body['input'])} input items..."

        if "prompt_cache_key" in body:
            body["prompt_cache_key"] = re.sub(
                r"(...)(.*)(...)", "\\1***\\3", body["prompt_cache_key"]
            )
        report = {
            "endpoint": re.sub(
                r"(//.)(.*?)(.\.)", "\\1***\\3", request_kwargs.get("url")
            ),
            "azure_status_code": resp.status_code,
            "azure_response": resp_content,
            "request_body": body,
        }
        # Precompute pretty JSON to avoid backslashes inside f-string expressions
        report_pretty = json.dumps(report, indent=4).replace("\n", "\n\t")
        error_message = (
            '\nCheck "azure_response" for the error details:\n'
            f"\t{report_pretty}\n"
            "If the issue persists, report it to:\n"
            "\thttps://github.com/gabrii/Cursor-Azure-GPT-5/issues\n"
            "Including all the details above"
        )
        console.rule(f"[red]Request failed with status code {resp.status_code}[/red]")
        console.print(error_message)
        return Response(
            error_message,
            status=resp.status_code if resp.status_code != 401 else 400,
        )
