"""Functional tests using WebTest.

See: http://webtest.readthedocs.org/
"""

import importlib
import json
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
        assert settings.AZURE_MODEL_DEPLOYMENTS["gpt-5"] == "gpt-5"
        assert settings.AZURE_MODEL_DEPLOYMENTS["gpt-5.5"] == "gpt-5.5"

    def test_optional_azure_settings_use_defaults_when_missing(self, monkeypatch):
        """Import settings without optional Azure env vars."""
        monkeypatch.setattr(environs.Env, "read_env", lambda *args, **kwargs: None)
        for key in (
            "AZURE_API_VERSION",
            "AZURE_SUMMARY_LEVEL",
            "AZURE_VERBOSITY_LEVEL",
            "AZURE_TRUNCATION",
        ):
            monkeypatch.delenv(key, raising=False)

        sys.modules.pop("app.settings", None)
        settings = importlib.import_module("app.settings")

        assert settings.AZURE_API_VERSION == "2025-04-01-preview"
        assert settings.AZURE_SUMMARY_LEVEL == "detailed"
        assert settings.AZURE_VERBOSITY_LEVEL == "medium"
        assert settings.AZURE_TRUNCATION == "disabled"

    def test_env_example_exposes_model_deployments_mapping(self, monkeypatch):
        """Load explicit per-model deployment overrides from the environment."""
        monkeypatch.setenv(
            "AZURE_MODEL_DEPLOYMENTS",
            json.dumps(
                {
                    "gpt-5.4": "prod-gpt54",
                    "gpt-5.4-mini": "team-mini",
                    "gpt-5.5": "gpt-5.5-1",
                }
            ),
        )

        sys.modules.pop("app.settings", None)
        settings = importlib.import_module("app.settings")

        assert settings.AZURE_MODEL_DEPLOYMENTS["gpt-5.4"] == "prod-gpt54"
        assert settings.AZURE_MODEL_DEPLOYMENTS["gpt-5.4-mini"] == "team-mini"
        assert settings.AZURE_MODEL_DEPLOYMENTS["gpt-5.5"] == "gpt-5.5-1"
        assert settings.AZURE_MODEL_DEPLOYMENTS["gpt-5"] == "gpt-5"

    def test_legacy_single_deployment_env_is_ignored(self, monkeypatch):
        """Do not silently backfill the old single-deployment env var."""
        monkeypatch.setenv("AZURE_DEPLOYMENT", "legacy-custom-deployment")

        sys.modules.pop("app.settings", None)
        settings = importlib.import_module("app.settings")

        assert settings.AZURE_MODEL_DEPLOYMENTS["gpt-5"] == "gpt-5"
