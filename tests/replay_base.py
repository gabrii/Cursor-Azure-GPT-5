"""Functional tests using WebTest.

See: http://webtest.readthedocs.org/
"""

import json
import os
import re
from typing import Any

from requests_mock import MockerCore
from webtest import TestApp


class ReplyBase:
    """Tests the replay of /recordings/<recording>/.

    This class is extensible via the ``recording`` attribute, which determines
    which subdirectory under ``tests/recordings/`` to load fixtures from.
    """

    # The subdirectory under tests/recordings/ to load fixtures from
    recording: str

    # Endpoint to mock for the upstream request
    UPSTREAM_URL = "https://test-resource.openai.azure.com/openai/responses?api-version=2025-04-01-preview"

    def _get_request_path(self, kind: str) -> str:
        """Return path for a recorded request JSON of given kind.

        Example: kind="upstream" -> tests/recordings/<recording>/upstream_request.json
        """
        return os.path.join(
            "tests", "recordings", self.recording, f"{kind}_request.json"
        )

    def _get_response_path(self, kind: str) -> str:
        """Return path for a recorded response SSE of given kind.

        Example: kind="downstream" -> tests/recordings/<recording>/downstream_response.sse
        """
        return os.path.join(
            "tests", "recordings", self.recording, f"{kind}_response.sse"
        )

    def _normalize_response(self, sse_response: bytes) -> str:
        """Normalize the response id and created timestamp (use re.sub)."""
        text = sse_response.decode("utf-8")
        text = re.sub(
            r'data: {"id":"chatcmpl-(.*?)"', 'data: {"id":"chatcmpl-ABC123"', text
        )
        text = re.sub(r'"created":(\d+)', '"created":1234567890', text)
        return text

    def _mock_upstream(self, requests_mock: MockerCore) -> Any:
        """Mock upstream request with recorded SSE upstream response.

        Returns the mock object so callers can inspect ``last_request``.
        """
        upstream_response_path = self._get_response_path("upstream")
        return requests_mock.post(
            self.UPSTREAM_URL,
            body=open(
                upstream_response_path, "rb"
            ),  # Yes, we need to pass the file object here, not the .read() result
        )

    def _perform_downstream_request(self, testapp: TestApp):
        """Perform recorded downstream request and return the response."""
        downstream_request_path = self._get_request_path("downstream")
        with open(downstream_request_path, "r") as f:
            downstream_request = f.read()
        return testapp.post(
            "/chat/completions",
            status=200,
            params=downstream_request,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer test-service-api-key",
            },
        )

    def _verify_upstream_request(self, mock: Any) -> None:
        """Verify upstream request matches the recorded upstream request."""
        upstream_request_path = self._get_request_path("upstream")
        with open(upstream_request_path, "r") as f:
            upstream_request = json.load(f)
        assert mock.last_request.json() == upstream_request

    def _verify_downstream_response(self, response) -> None:
        """Verify downstream response matches the recorded downstream response."""
        downstream_response_path = self._get_response_path("downstream")
        with open(downstream_response_path, "rb") as f:
            recorded_downstream_response = f.read()
        response_normalized = self._normalize_response(response.body)
        recorded_response_normalized = self._normalize_response(
            recorded_downstream_response
        )
        assert response_normalized == recorded_response_normalized

    def test(self, testapp: TestApp, requests_mock: MockerCore):
        """Run the replay flow using the configured recording fixtures."""
        mock = self._mock_upstream(requests_mock)
        response = self._perform_downstream_request(testapp)
        self._verify_upstream_request(mock)
        self._verify_downstream_response(response)
