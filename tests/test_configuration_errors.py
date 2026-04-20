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

\tModel name must be one of:
\t  gpt-5.4, gpt-5.4-none, gpt-5.4-low, gpt-5.4-medium, gpt-5.4-high, gpt-5.4-xhigh
\t  gpt-5.4-mini, gpt-5.4-mini-none, gpt-5.4-mini-low, gpt-5.4-mini-medium, gpt-5.4-mini-high, gpt-5.4-mini-xhigh
\t  gpt-high, gpt-medium, gpt-low, gpt-minimal
\t
\tGot: foo-minimal"""

    @property
    def downstream_request_body(self) -> str:
        """Set invalid model name in request body."""
        return super().downstream_request_body.replace("gpt-", "foo-")


class TestBareModelWithoutReasoning(ReplyBase):
    """Require Cursor's native reasoning field for bare model names."""

    expected_upstream_request_body = None
    expected_downstream_status_code = 400
    expected_downstream_response_body = b"""Cursor configuration error, check your Cursor settings.

\tCursor must send reasoning.effort when using bare model names like gpt-5.4."""

    @property
    def downstream_request_body(self) -> str:
        """Use a bare model name without the native reasoning field."""
        return super().downstream_request_body.replace(
            '"model": "gpt-minimal"', '"model": "gpt-5.4"'
        )
