"""Functional tests using WebTest.

See: http://webtest.readthedocs.org/
"""

from .replay_base import ReplyBase


class TestOnePingPong(ReplyBase):
    """Test a single ping-pong interaction, no tool calls."""

    recording = "one_ping_pong"


class TestMultiplePingPongs(ReplyBase):
    """Test multiple ping-pong interactions back and forth, no tool calls."""

    recording = "multiple_ping_pongs"


class TestContextWithSingleToolCalls(ReplyBase):
    """Multiple single tool calls in the context."""

    recording = "context_single_tool_calls"


class TestReplyWithSingleToolCall(ReplyBase):
    """Single tool call in the reply."""

    recording = "reply_single_tool_call"


class TestContextWithParallelToolCall(ReplyBase):
    """Parallel tool calls in the context."""

    recording = "context_parallel_tool_call"


class TestReplyWithParallelToolCall(ReplyBase):
    """Parallel tool calls in the reply."""

    recording = "reply_parallel_tool_call"


class TestReplyVerbosityLevelHigh(ReplyBase):
    """Reply with verbosity level set to high."""

    def modify_settings(self, app):
        """Sets verbosity level to high."""
        app.config["AZURE_VERBOSITY_LEVEL"] = "high"

    recording = "verbosity_level"
