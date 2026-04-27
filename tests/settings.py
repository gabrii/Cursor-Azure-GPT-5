"""Settings module for test app."""

from app.models import SUPPORTED_MODELS

ENV = "development"
TESTING = True

SERVICE_API_KEY = "test-service-api-key"

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
