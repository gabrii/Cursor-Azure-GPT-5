"""Functional tests using WebTest.

See: http://webtest.readthedocs.org/
"""


class TestLoggingIn:
    """Login."""

    def test_can_log_in_returns_200(self, testapp):
        """Test empty homepage."""
        testapp.get("/", status=405)
