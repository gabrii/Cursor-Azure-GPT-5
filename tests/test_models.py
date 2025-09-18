"""Functional tests using WebTest.

See: http://webtest.readthedocs.org/
"""


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
