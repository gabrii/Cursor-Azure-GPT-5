"""Defines fixtures available to all tests."""

import logging

import pytest
from flask import Flask
from webtest import TestApp

from app import create_app


@pytest.fixture
def app() -> Flask:
    """Create application for the tests."""
    _app = create_app("tests.settings")
    _app.logger.setLevel(logging.CRITICAL)
    ctx = _app.test_request_context()
    ctx.push()

    yield _app

    ctx.pop()


@pytest.fixture
def testapp(app) -> TestApp:
    """Create Webtest app."""
    return TestApp(app)
