"""Functional tests using WebTest.

See: http://webtest.readthedocs.org/
"""

import os

from app.common import recording

from .replay_base import ReplyBase


class TestRecording(ReplyBase):
    """Test a single ping-pong interaction, no tool calls."""

    def modify_settings(self, app):
        """Enables traffic recording."""
        app.config["RECORD_TRAFFIC"] = True

    def test(self, testapp, requests_mock, monkeypatch, tmp_path):
        """Test recording."""
        monkeypatch.setattr(recording, "RECORDINGS_DIR", tmp_path)
        monkeypatch.setattr(recording, "__LAST_RECORDING_INDEX", 0)
        super().test(testapp, requests_mock)
        directories = os.listdir(tmp_path)
        assert len(directories) == 1
        directory = directories[0]
        assert directory.isdigit()
        assert directory == "1"
        assert os.path.exists(
            os.path.join(tmp_path, directory, "upstream_request.json")
        )
        assert os.path.exists(
            os.path.join(tmp_path, directory, "upstream_response.sse")
        )
        assert os.path.exists(
            os.path.join(tmp_path, directory, "downstream_request.json")
        )
        assert os.path.exists(
            os.path.join(tmp_path, directory, "downstream_response.sse")
        )

        super().test(testapp, requests_mock)
        directories = os.listdir(tmp_path)
        assert len(directories) == 2
