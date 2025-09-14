"""Azure adapter orchestrating request/response transformations."""

from __future__ import annotations

from typing import Optional

import requests
from flask import Request, Response

from ..common.recording import record_payload

# Local adapters
from .request_adapter import RequestAdapter
from .response_adapter import ResponseAdapter


class AzureAdapter:
    """Orchestrate forwarding of a Flask Request to Azure's Responses API.

    Provides a Completions-compatible interface to the caller by composing a
    RequestAdapter (pre-request transformations) and a ResponseAdapter
    (post-request transformations). The adapters receive a reference to this
    instance for shared per-request state (models/early_response).
    """

    # Per-request state (streaming completions only)
    inbound_model: Optional[str] = None
    early_response: Optional[Response] = None

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
           on this adapter (models) or sets early_response.
        2) Perform the upstream HTTP call using a short-lived requests call.
        3) ResponseAdapter converts the upstream response into a Flask Response.
        """
        request_kwargs = self.request_adapter.adapt(req)

        # Allow early short-circuit responses (e.g., config errors)
        if self.early_response is not None:
            return self.early_response

        record_payload(request_kwargs.get("json", {}), "upstream_request")

        # Perform upstream request with kwargs directly (no long-lived session)
        resp = requests.request(**request_kwargs)

        return self.response_adapter.adapt(resp)
