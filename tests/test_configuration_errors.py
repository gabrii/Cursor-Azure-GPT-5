"""Functional tests using WebTest.

See: http://webtest.readthedocs.org/
"""

from .replay_base import ReplyBase


class TestBadSummaryLevel(ReplyBase):
    """Test a single ping-pong interaction, no tool calls."""

    expected_upstream_request_body = None
    expected_downstream_status_code = 400
    expected_downstream_response_body = b"""Service configuration error, check your .env file.

\tAZURE_SUMMARY_LEVEL must be either auto, detailed, or concise.
\t
\tGot: foo"""

    def modify_settings(self, app) -> None:
        """Set invalid summary level in settings."""
        app.config["AZURE_SUMMARY_LEVEL"] = "foo"


class TestBadModelName(ReplyBase):
    """Test a single ping-pong interaction, no tool calls."""

    expected_upstream_request_body = None
    expected_downstream_status_code = 400
    expected_downstream_response_body = b"""Cursor configuration error, check your Cursor settings.

\tModel name must be either gpt-high, gpt-medium, gpt-low, or gpt-minimal.
\t
\tGot: foo-minimal"""

    @property
    def downstream_request_body(self) -> str:
        """Set invalid model name in request body."""
        return super().downstream_request_body.replace("gpt-", "foo-")
