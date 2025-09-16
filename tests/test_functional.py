"""Functional tests using WebTest.

See: http://webtest.readthedocs.org/
"""


class TestConfig:
    """Config."""

    def test_config_is_set(self, testapp):
        """Ensure required config values are set."""
        app = testapp.app
        assert app.config["AZURE_BASE_URL"] != "change_me"
        assert app.config["AZURE_API_KEY"] != "change_me"


class TestModels:
    """Models."""

    def test_models_endpoint_returns_400(self, testapp):
        """Ensure /models endpoint returns HTTP 400."""
        testapp.get("/models", status=400)

    def test_health_endpoint_returns_200(self, testapp):
        """Ensure /health endpoint returns HTTP 200."""
        testapp.get("/health", status=200)
