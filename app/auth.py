"""Authentication module."""

from functools import wraps

from flask import Response, current_app, request


def valid_brearer_token():
    """Validate the bearer token."""
    service_api_key = current_app.config["SERVICE_API_KEY"]
    return request.authorization and request.authorization.token == service_api_key


def require_auth(func):
    """Require authentication for the given route."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        """Wrapper function return Unauthorized if the token is invalid."""
        if valid_brearer_token():
            return func(*args, **kwargs)
        else:
            error_message = (
                "\nAuthentication with Cursor-Azure-GPT-5 service failed.\n\n"
                "These value of:\n"
                "\tCursor Settings > Models > API Keys > OpenAI API Key\n\n"
                "Must match the value of:\n"
                "\tSERVICE_API_KEY in your .env file\n\n"
                "Ensure the values match exactly, and try again.\n"
                "If modifying the .env file, restart the service for the changes to apply."
            )
            return Response(error_message, 400)

    return wrapper
