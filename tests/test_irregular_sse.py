"""Functional tests using WebTest.

See: http://webtest.readthedocs.org/
"""

from .replay_base import ReplyBase


class TestSSEWithoutClosingNewLines(ReplyBase):
    """Test the replay of an SSE response without closing new lines."""

    recording = "sse_without_closing_new_lines"
