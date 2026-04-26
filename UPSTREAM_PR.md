# Pull request: changes vs [gabrii/Cursor-Azure-GPT-5](https://github.com/gabrii/Cursor-Azure-GPT-5)

This document summarizes everything on `main` in this fork that is **not** on upstream `main`. It is based on `git diff gabrii/main..HEAD` and the current tree.

## Scope

- **Upstream ref:** `gabrii/main`
- **Merge base:** `45c5874` (upstream merge of PR #87 from `dat-nguyen96/main`)
- **Commits ahead of upstream:** 14
- **Main change areas:** request/response adapters, model mapping, token-usage tooling, docs, Docker/runtime, tests, and recordings

## Executive summary

This fork makes the proxy Cursor-native for Azure Responses. It accepts Cursor's Chat Completions and Responses payloads, translates Cursor and tool streaming shapes correctly, routes caching by conversation id, surfaces usage/cache details back to Cursor, and replaces legacy alias-based model handling with explicit supported model ids plus an Azure deployment map.

## 1. Compatibility: Cursor request and response shapes

- Accepts both **Chat Completions** style (`messages`) and **Responses API** style (`input` / `instructions`), and passes native Responses payloads through instead of rewriting them.
- Transforms Chat-style `tools[].function` into Responses-style tools, but also passes through tools that are already in Responses format.
- Updates request logging so it understands both tool shapes.
- `SSEEvent.json` now treats `[DONE]` as a non-JSON sentinel instead of trying to parse it.
- The streaming adapter now handles `custom_tool_call`, `custom_tool_call_input.delta`, `response.error`, `response.failed`, `response.incomplete`, `reasoning_text`, `refusal`, MCP failures, audio transcript events, code interpreter code events, and several native tool item types such as `apply_patch_call`, `shell_call`, `local_shell_call`, `mcp_call`, and `computer_call`.
- Benign lifecycle events are intentionally silenced, but unknown SSE events are logged so they are no longer dropped silently.
- Cursor's native `reasoning.effort` is forwarded directly, and bare model ids must include that reasoning field.

## 2. Prompt caching and routing

- Upstream requests now set **`store: true`**.
- **`prompt_cache_key`** is derived from `metadata.cursorConversationId` when present, instead of Cursor's `user` field.
- **`session_id`** and **`x-client-request-id`** headers are set to the same conversation id to improve cache affinity.
- **`parallel_tool_calls: true`** is always set.
- **`service_tier`** and **`include`** are forwarded when Cursor sends them.
- **`include_usage`** is stripped before calling Azure Responses, but the adapter remembers the flag and emits a terminal usage chunk afterward when Cursor asked for usage.
- Final usage reporting now includes **cached tokens** and **reasoning tokens**, and `response.completed` logs a `USAGE:` line with cache-hit percentage.

## 3. Model surface and Azure deployment mapping

- `app/models.py` adds the supported model list: `gpt-5`, `gpt-5-mini`, `gpt-5-codex`, `gpt-5.1`, `gpt-5.1-codex`, `gpt-5.1-codex-max`, `gpt-5.1-codex-mini`, `gpt-5.2`, `gpt-5.2-codex`, `gpt-5.3-codex`, `gpt-5.4`, `gpt-5.4-mini`, and `gpt-5.4-nano`.
- Legacy alias ids like `gpt-high`, `gpt-medium`, `gpt-low`, and `gpt-minimal` are removed from the public surface.
- `AZURE_MODEL_DEPLOYMENTS` is now a validated JSON mapping from Cursor-facing model id to Azure deployment name.
- `create_app()` copies the deployment map so app instances do not share mutable config state.
- The `/models` endpoint now returns the supported model list directly from the shared model metadata.
- Using these normal Cursor model ids is the point: you just pick them in Cursor like any other first-class model, so Cursor can apply the right built-in model behavior and prompt framing without inventing custom aliases.
- That also keeps the UI and the proxy aligned with the actual model names users expect to select, instead of asking them to think in terms of custom proxy-only ids.

## 4. Token usage and cost visibility

- `app/common/token_usage_report.py` parses `USAGE:` log lines, aggregates token totals, estimates spend, and computes cache hit rate and request-size percentiles.
- `scripts/analyze_token_usage.py` reads Docker Compose logs and renders a report for the proxy's usage history.
- The proxy now forwards enough usage detail for Cursor and the logs to reflect cache and reasoning token accounting.

## 5. Reliability and operator experience

- Recording failures are non-fatal, so optional upstream/downstream fixture writing cannot take down the proxy.
- Request/error logging was cleaned up, and Azure error responses now redact request fields more carefully.
- Authentication helper naming and messaging were cleaned up.
- `.env` is no longer baked into the Docker image.
- `docker-compose.yml` now separates the production proxy service from the dev profile, adds a healthcheck, and loads secrets at runtime.
- `start.sh` bootstraps a local virtualenv and prints the Cursor setup values for a quick local run.
- `README.md` and `AGENTS.md` were refreshed to match the new fork behavior and setup.

## 6. Tests and fixtures

- New tests cover request adaptation, response adaptation, token-usage parsing, model validation, config behavior, and updated error paths.
- Replay fixtures under `tests/recordings/` were updated for the new request and SSE shapes.
- The typo in `tests/test_commnads.py` was fixed by renaming it to `tests/test_commands.py`.

## Suggested PR title

`Cursor-native Azure Responses proxy: tools, SSE, caching, usage, and deployment mapping`

## Suggested PR body

Use the executive summary plus sections 1 through 6 above.
