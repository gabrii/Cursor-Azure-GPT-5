"""Functional tests using WebTest.

See: http://webtest.readthedocs.org/
"""

import os

from app.common import recording

from .replay_base import ReplyBase


class TestRecording(ReplyBase):
    """Test different scenarios with traffic recording enabled."""

    def modify_settings(self, app):
        """Enables traffic recording."""
        app.config["RECORD_TRAFFIC"] = True

    def test_multiple_requests(self, testapp, requests_mock, monkeypatch, tmp_path):
        """Test two consecutive requests."""
        monkeypatch.setattr(recording, "RECORDINGS_DIR", tmp_path)
        monkeypatch.setattr(recording, "__LAST_RECORDING_INDEX", -1)

        super().test(testapp, requests_mock)

        directories = os.listdir(tmp_path)
        assert len(directories) == 1, "First directory created"

        directory = directories[0]
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
        assert len(directories) == 2, "Second directory created"

    def test_creates_folder(self, testapp, requests_mock, monkeypatch, tmp_path):
        """Test recordings folder is created."""
        recordings_path = os.path.join(tmp_path, "recordings")
        monkeypatch.setattr(recording, "RECORDINGS_DIR", recordings_path)
        monkeypatch.setattr(recording, "__LAST_RECORDING_INDEX", -1)

        assert not os.path.exists(recordings_path)

        super().test(testapp, requests_mock)

        assert os.path.exists(recordings_path)
        assert os.path.exists(os.path.join(recordings_path, "1"))

    def test_increments_index(self, testapp, requests_mock, monkeypatch, tmp_path):
        """Test that the index for the next recording is incremented, and ignores unrelated folders."""
        monkeypatch.setattr(recording, "RECORDINGS_DIR", tmp_path)
        monkeypatch.setattr(recording, "__LAST_RECORDING_INDEX", -1)

        # Last recording index 123
        os.makedirs(os.path.join(tmp_path, "123"))

        # Unrelated folder
        os.makedirs(os.path.join(tmp_path, "foo"))

        # Smaller index than last recording index
        os.makedirs(os.path.join(tmp_path, "-10"))

        super().test(testapp, requests_mock)

        assert os.path.exists(os.path.join(tmp_path, "124"))
