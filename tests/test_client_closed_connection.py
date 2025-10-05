"""Tests for client-closed connection during streaming.

This test simulates a downstream client closing the connection mid-stream by
forcing a GeneratorExit inside the streaming pipeline. The outer boundary in
ResponseAdapter should translate that into ClientClosedConnection.
"""

import pytest

from app.exceptions import ClientClosedConnection
from tests.replay_base import ReplyBase


def _raise_generator_exit(
    _chunks,
):  # pragma: no cover - behavior is validated via exception
    """Stub encoder that simulates generator shutdown.

    Raising GeneratorExit here mimics the server-side observation that the
    response iterable was closed. We don't yield any bytes.
    """
    raise GeneratorExit


class TestClientClosedConnection(ReplyBase):
    """Ensure a client disconnect is surfaced as ClientClosedConnection."""

    # Use any existing recording that yields a normal streaming response
    recording: str = "one_ping_pong"

    def test(self, testapp, requests_mock, monkeypatch):
        # Patch the exact symbol used inside ResponseAdapter to encode SSE
        monkeypatch.setattr(
            "app.azure.response_adapter.chunks_to_sse", _raise_generator_exit
        )

        # Mock upstream with recorded SSE so the adapter enters streaming code
        mock = self.mock_upstream(requests_mock)

        # When the streaming pipeline is interrupted, the adapter should raise
        # our domain-specific exception. No response bytes should be produced.
        with pytest.raises(ClientClosedConnection):
            testapp.post(
                "/chat/completions",
                params=self.downstream_request_body,
                headers=self.downstream_request_headers,
            )

        # Sanity check: upstream was called with the expected payload
        self.assert_upstream_request(mock)
