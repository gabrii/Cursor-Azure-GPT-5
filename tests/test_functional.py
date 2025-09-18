"""Functional tests using WebTest.

See: http://webtest.readthedocs.org/
"""

import environs


class TestConfig:
    """Config."""

    def test_config_is_set(self, testapp):
        """Ensure required config values are set."""
        app = testapp.app
        assert app.config["AZURE_BASE_URL"] != "change_me"
        assert app.config["AZURE_API_KEY"] != "change_me"

    def test_default_settings_load(self, monkeypatch):
        """Patch Env.read_env to read from .env.example and import settings."""
        orig_read_env = environs.Env.read_env
        monkeypatch.setattr(
            environs.Env,
            "read_env",
            lambda *args, **kwargs: orig_read_env(
                ".env.example", override=True, **kwargs
            ),
        )

        from app import settings

        assert settings.AZURE_BASE_URL == "https://change-me.openai.azure.com"


class TestModels:
    """Models."""

    def test_models_endpoint_returns_400(self, testapp):
        """Ensure /models endpoint returns HTTP 400."""
        testapp.get("/models", status=400)

    def test_models_endpoint_returns_200(self, testapp):
        """Ensure /models endpoint returns HTTP 400."""
        response = testapp.get(
            "/models",
            status=200,
            headers={"Authorization": "Bearer test-service-api-key"},
        )
        content = response.body.decode("utf-8")
        assert '"gpt-high"' in content
        assert '"gpt-medium"' in content
        assert '"gpt-low"' in content
        assert '"gpt-minimal"' in content

    def test_health_endpoint_returns_200(self, testapp):
        """Ensure /health endpoint returns HTTP 200."""
        testapp.get("/health", status=200)
