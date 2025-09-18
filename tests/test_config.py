"""Functional tests using WebTest.

See: http://webtest.readthedocs.org/
"""

import importlib
import sys

import environs


class TestConfig:
    """Config."""

    def test_test_config_is_set(self, testapp):
        """Ensure that test config is set."""
        app = testapp.app
        assert app.config["AZURE_BASE_URL"] != "change_me"
        assert app.config["AZURE_API_KEY"] != "change_me"

    def test_env_example_loads(self, monkeypatch):
        """Patch Env.read_env to read from .env.example and import settings."""
        orig_read_env = environs.Env.read_env
        monkeypatch.setattr(
            environs.Env,
            "read_env",
            lambda *args, **kwargs: orig_read_env(
                ".env.example", override=True, **kwargs
            ),
        )

        sys.modules.pop("app.settings", None)
        settings = importlib.import_module("app.settings")

        assert settings.AZURE_BASE_URL == "https://change-me.openai.azure.com"
