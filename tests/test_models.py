"""Functional tests using WebTest.

See: http://webtest.readthedocs.org/
"""

from app.models import SUPPORTED_MODELS


class TestModels:
    """Models."""

    def test_models_endpoint_returns_400(self, testapp):
        """Ensure /models endpoint returns HTTP 400 without auth."""
        testapp.get("/models", status=400)

    def test_models_endpoint_returns_200(self, testapp):
        """Ensure /models endpoint returns HTTP 200 with auth."""
        response = testapp.get(
            "/models",
            status=200,
            headers={"Authorization": "Bearer test-service-api-key"},
        )
        payload = response.json
        returned_models = [item["id"] for item in payload["data"]]

        assert returned_models == list(SUPPORTED_MODELS)
        assert "gpt-5.5" in returned_models
        assert "gpt-high" not in returned_models
        assert "gpt-medium" not in returned_models
        assert "gpt-low" not in returned_models
        assert "gpt-minimal" not in returned_models

    def test_health_endpoint_returns_200(self, testapp):
        """Ensure /health endpoint returns HTTP 200 without auth."""
        testapp.get("/health", status=200)
