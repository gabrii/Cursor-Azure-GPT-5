"""Settings module for test app."""

ENV = "development"
TESTING = True

SERVICE_API_KEY = "test-service-api-key"

AZURE_API_VERSION = "2025-04-01-preview"
AZURE_BASE_URL = "https://test-resource.openai.azure.com"
AZURE_API_KEY = "test-api-key"
AZURE_DEPLOYMENT = "gpt-5"
AZURE_SUMMARY_LEVEL = "detailed"
AZURE_TRUNCATION = "auto"

RECORD_TRAFFIC = False


AZURE_RESPONSES_API_URL = (
    f"{AZURE_BASE_URL}/openai/responses?api-version={AZURE_API_VERSION}"
)
