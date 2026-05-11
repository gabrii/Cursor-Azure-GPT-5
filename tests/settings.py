"""Settings module for test app."""

from app.models import SUPPORTED_MODELS

ENV = "development"
TESTING = True

SERVICE_API_KEY = "test-service-api-key"

ENABLE_AZURE = True
ENABLE_CODEX = True

AZURE_BASE_URL = "https://test-resource.openai.azure.com"
AZURE_API_KEY = "test-api-key"
AZURE_MODEL_DEPLOYMENTS = {model: model for model in SUPPORTED_MODELS}
AZURE_SUMMARY_LEVEL = "detailed"
AZURE_VERBOSITY_LEVEL = "medium"
AZURE_TRUNCATION = "disabled"

RECORD_TRAFFIC = False
LOG_CONTEXT = True
LOG_COMPLETION = True


AZURE_RESPONSES_API_URL = f"{AZURE_BASE_URL}/openai/v1/responses"

CODEX_AUTH_PATH = "~/.codex/auth.json"
CODEX_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
CODEX_SUPPORTED_MODELS = ("codex-test-model", "codex-other-model")
CODEX_MODEL_REWRITES = {}
CODEX_ORIGINATOR = "codex_cli_rs"
CODEX_USER_AGENT = "test-agent"
CODEX_DISCOVERY_MODE = True
CODEX_TOKEN_REFRESH_SKEW_SECONDS = 300
CODEX_REQUEST_TIMEOUT_SECONDS = 600.0
