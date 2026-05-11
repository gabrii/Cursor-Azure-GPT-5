# Azure-Rooted Multi-Provider Proxy

## Status

Accepted.

## Context

The existing public product is the Cursor Azure GPT-5 Flask proxy. A separate Codex proxy proved useful for routing Cursor traffic to the Codex/ChatGPT backend, backed by a ChatGPT monthly subscription through `codex login`.

Keeping the providers as separate services duplicated the Cursor-facing contract, deployment surface, and documentation.

## Decision

Keep this repository Azure-rooted for backward compatibility. Root paths (`/`) and explicit `/azure` paths route to Azure. Codex is available through `/codex`.

Azure and Codex are first-class peer providers. Provider selection is path-based instead of model-based because both providers can expose overlapping model IDs. Model lists are provider-local:

- `/v1/models` and `/azure/v1/models` return Azure models.
- `/codex/v1/models` returns Codex/ChatGPT subscription models.

`ENABLE_AZURE` and `ENABLE_CODEX` disable providers locally. A disabled provider returns a local error and never falls back to another provider.

Both providers share `SERVICE_API_KEY` by default so Cursor clients can switch providers by changing only the base URL path.

## Consequences

Azure users keep the existing root URL and environment variables. Codex users get the ported request adaptation, response adaptation, auth-state handling, and token refresh behavior under the same Flask server stack.

Codex is not a fallback for Azure. It is the explicit provider path for users who want to use a ChatGPT monthly subscription from Cursor.
