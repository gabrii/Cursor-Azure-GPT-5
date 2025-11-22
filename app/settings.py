"""Application configuration.

Most configuration is set via environment variables.

For local development, use a .env file to set
environment variables.
"""

from environs import Env

env = Env()
env.read_env()

ENV = env.str("FLASK_ENV", default="production")
DEBUG = ENV == "development"
RECORD_TRAFFIC = env.bool("RECORD_TRAFFIC", False)
LOG_CONTEXT = env.bool("LOG_CONTEXT", True)
LOG_COMPLETION = env.bool("LOG_COMPLETION", True)

SERVICE_API_KEY = env.str("SERVICE_API_KEY", "change-me")

AZURE_BASE_URL = env.str("AZURE_BASE_URL", "change_me").rstrip("/")
AZURE_API_KEY = env.str("AZURE_API_KEY", "change_me")
AZURE_DEPLOYMENT = env.str("AZURE_DEPLOYMENT") or "gpt-5"

AZURE_API_VERSION = env.str("AZURE_API_VERSION") or "2025-04-01-preview"
AZURE_SUMMARY_LEVEL = env.str("AZURE_SUMMARY_LEVEL") or "detailed"
AZURE_VERBOSITY_LEVEL = env.str("AZURE_VERBOSITY_LEVEL") or "medium"
AZURE_TRUNCATION = env.str("AZURE_TRUNCATION") or "disabled"

AZURE_RESPONSES_API_URL = (
    f"{AZURE_BASE_URL}/openai/responses?api-version={AZURE_API_VERSION}"
)
