"""Functional tests using WebTest.

See: http://webtest.readthedocs.org/
"""

import json
import os
import re
from io import BytesIO
from typing import Any, Dict

from requests_mock import MockerCore
from webtest import TestApp


class ReplyBase:
    """Tests the replay of /recordings/<recording>/.

    This class is extensible via the ``recording`` attribute, which determines
    which subdirectory under ``tests/recordings/`` to load fixtures from.
    """

    # The subdirectory under tests/recordings/ to load fixtures from
    recording: str = "default_recording"
    upstream_status_code: int = 200
    expected_downstream_status_code: int = 200

    # Endpoint to mock for the upstream request
    UPSTREAM_URL = "https://test-resource.openai.azure.com/openai/responses?api-version=2025-04-01-preview"

    def _get_recording_path(self, file_name: str) -> str:
        return os.path.join("tests", "recordings", self.recording, file_name)

    def _get_request_body(self, kind: str) -> str:
        request_path = self._get_recording_path(f"{kind}_request.json")
        with open(request_path, "r") as f:
            return f.read()

    def _get_response_body(self, kind: str) -> bytes:
        response_path = self._get_recording_path(f"{kind}_response.sse")
        with open(response_path, "rb") as f:
            return f.read()

    @property
    def expected_upstream_request_body(self) -> str:
        """Return recorded upstream request JSON string."""
        return self._get_request_body("upstream")

    @property
    def downstream_request_body(self) -> str:
        """Return recorded downstream request JSON string."""
        return self._get_request_body("downstream")

    @property
    def upstream_response_body(self) -> bytes:
        """Return recorded upstream response SSE bytes."""
        return self._get_response_body("upstream")

    @property
    def expected_downstream_response_body(self) -> bytes:
        """Return recorded downstream response SSE bytes."""
        return self._get_response_body("downstream")

    @property
    def downstream_request_headers(self) -> Dict[str, str]:
        """Return headers for the downstream request."""
        return {
            "Content-Type": "application/json",
            "Authorization": "Bearer test-service-api-key",
        }

    def _normalize_response(self, sse_response: bytes) -> str:
        """Normalize the response id and created timestamp (use re.sub)."""
        text = sse_response.decode("utf-8")
        text = re.sub(
            r'data: {"id":"chatcmpl-(.*?)"', 'data: {"id":"chatcmpl-ABC123"', text
        )
        text = re.sub(r'"created":(\d+)', '"created":1234567890', text)
        return text

    def mock_upstream(self, requests_mock: MockerCore) -> Any:
        """Mock upstream request with recorded SSE upstream response.

        Returns the mock object so callers can inspect ``last_request``.
        """
        return requests_mock.post(
            self.UPSTREAM_URL,
            status_code=self.upstream_status_code,
            body=BytesIO(self.upstream_response_body),
        )

    def perform_downstream_request(self, testapp: TestApp):
        """Perform recorded downstream request and return the response."""

        return testapp.post(
            "/chat/completions",
            status=self.expected_downstream_status_code,
            params=self.downstream_request_body,
            headers=self.downstream_request_headers,
        )

    def assert_upstream_request(self, mock: Any) -> None:
        """Assert upstream request matches the recorded upstream request."""
        expected_upstream_request_json = json.loads(self.expected_upstream_request_body)
        assert mock.last_request.json() == expected_upstream_request_json

    def assert_downstream_response(self, response) -> None:
        """Assert downstream response matches the recorded downstream response."""
        response_normalized = self._normalize_response(response.body)
        expected_response_normalized = self._normalize_response(
            self.expected_downstream_response_body
        )
        assert response_normalized == expected_response_normalized

    def modify_settings(self, app) -> None:
        """Hook to allow subclasses to tweak app.config before running the test.

        Override in subclasses, e.g.:

            def modify_settings(self, app):
                app.config["RECORD_TRAFFIC"] = True
        """
        pass

    def test(self, testapp: TestApp, requests_mock: MockerCore):
        """Run the replay flow using the configured recording fixtures."""
        self.modify_settings(testapp.app)
        mock = self.mock_upstream(requests_mock)
        response = self.perform_downstream_request(testapp)
        self.assert_upstream_request(mock)
        self.assert_downstream_response(response)
