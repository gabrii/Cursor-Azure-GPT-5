# Cursor Azure and Codex GPT-5 Proxy

> **This project is back and actively maintained.** After months of dependency-only updates, the proxy has been overhauled with a complete rewrite of the request/response layer, full Responses API support, prompt caching, native reasoning controls, and much more. It is being used daily in production with Cursor. **If you run into issues, please [open an issue](https://github.com/gabrii/Cursor-Azure-GPT-5/issues)** — bug reports and feedback are essential to keep this working well for everyone.

A Flask proxy that lets **Cursor** use **Azure OpenAI** deployments or a **Codex/ChatGPT monthly subscription** as first-class OpenAI-compatible providers — with full support for streaming, reasoning, tool calls, and prompt caching where the upstream supports it.

Cursor sends standard OpenAI requests. This proxy translates them to the selected provider's Responses API on the fly, then streams back responses in the exact format Cursor expects. No Cursor modifications needed, no forks — just point and go. Use Azure when you want Azure-hosted deployments; use Codex when you want to drive Cursor from an existing ChatGPT monthly subscription.

> **You still need a paid Cursor plan.** This project only redirects where model traffic goes.

> [!IMPORTANT]
> **Using GPT-5.5 in Cursor? Read this first.**
>
> Cursor may currently fail to route direct `gpt-5.5` traffic through custom base URLs, causing errors such as `User API Key Rate limit exceeded`.
>
> The issue has already been reported to the Cursor team here: <https://forum.cursor.com/t/not-able-to-use-azure-api-key/149185/34>
>
> Use the documented temporary workaround instead: **[GPT-5.5 Cursor Routing Issue](#gpt-55-cursor-routing-issue)**.
---

## Why This Exists

Cursor talks OpenAI. Azure and Codex both speak Responses-style APIs with provider-specific auth, routing, event streams, and request details. This proxy sits in the middle and handles the translation — both directions, in real time, while streaming.

It was built to make both primary backends practical in Cursor:

- **Azure provider:** use your Azure OpenAI deployments with Cursor-native model IDs, reasoning effort controls, Azure prompt caching, and Azure Responses streaming.
- **Codex provider:** use your existing ChatGPT monthly subscription through Codex auth (`codex login`) from Cursor, with Codex request adaptation, Codex auth-state refresh, and Chat Completions compatibility.

Azure remains the root URL for backward compatibility. Codex is selected explicitly with `/codex`; it is not a secondary fallback path.

---

## Key Features

### First-Class Azure And Codex Providers

Azure and Codex are separate providers with separate model lists, separate upstream auth, and explicit routing:

- `/` and `/azure` route to Azure.
- `/codex` routes to the Codex/ChatGPT subscription provider.
- Both use the same Cursor-facing `SERVICE_API_KEY`.
- Disabling one provider returns a local error instead of falling through to the other.

This lets one public host serve Azure-backed Cursor clients and ChatGPT-subscription-backed Cursor clients at the same time. The two providers are peers: Codex is the primary path for ChatGPT monthly subscription users, while Azure is the primary path for Azure deployment users.

### Codex/ChatGPT Subscription Provider

The Codex provider makes a ChatGPT monthly subscription usable from Cursor through the same OpenAI-compatible request surface. It reads the local `codex login` ChatGPT auth state, refreshes access tokens when needed, forwards Cursor's Responses-shaped agent traffic to the Codex backend, and streams Responses SSE back as Chat Completions chunks for Cursor.

Codex has provider-local model discovery via `/codex/v1/models`, supports Cursor's `/codex/chat/completions` and `/codex/v1/chat/completions` shapes, preserves reasoning effort, forwards tool definitions and tool outputs, and uses per-conversation identity from Cursor metadata for upstream session/thread headers.

For users whose goal is to use a ChatGPT monthly subscription in Cursor, `/codex` is the intended base URL:

```text
https://your-public-proxy-url/codex
```

### Native Multi-Model Selection (No Legacy Aliases)

Unlike older proxy setups that forced you into one deployment or generic aliases like `gpt-high` / `gpt-medium`, this proxy exposes many Cursor-native models at the same time. Azure and Codex each publish their own provider-local model list, so you can keep `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, Codex variants, and other supported IDs available in Cursor's built-in model picker, then switch between them per chat exactly like you would with Cursor's default model selection.

The proxy uses Cursor's **real model IDs** (e.g. `gpt-5.4`, `gpt-5.4-mini`). This means **Cursor sends its tailored, model-specific system prompts** rather than generic fallbacks — resulting in noticeably better output quality, because each model gets the prompt engineering Cursor designed for it.

The proxy preserves Cursor's native `reasoning.effort` field and forwards it to the selected provider, so Cursor's thinking controls (low / medium / high) work exactly as intended when the upstream model supports them.

### Azure Prompt Caching with Per-Conversation Affinity

For Azure, the proxy extracts `metadata.cursorConversationId` from each request and uses it as the cache routing key. For every Azure conversation it sets:

- `prompt_cache_key` = conversation ID
- `session_id` = conversation ID (pins requests to the same Azure backend machine)
- `x-client-request-id` = conversation ID (per-conversation request correlation)
- `store: true` (enables Azure server-side storage for 24h cache retention)
- `parallel_tool_calls: true`

This means long Azure-backed Cursor conversations reuse their prompt cache across turns, significantly reducing input token costs and latency. The proxy logs cache hit rates per request (`USAGE:` lines) and includes `prompt_tokens_details.cached_tokens` in the response so Cursor can display cache statistics.

In real Cursor agent sessions, mature conversations regularly hit the practical ceiling for prompt caching — often **99%+ cached input tokens** once the stable context is warm. Parallel tool calls, subagents, and multiple concurrent agent flows can run without throwing away the cache, because each conversation keeps its own cache key and Azure backend affinity instead of sharing one global user bucket.

> **Why this matters:** The `user` field is a per-user hash shared across all conversations — using it for cache routing would mix unrelated conversations on the same cache partition. This proxy explicitly routes by conversation ID instead.

### Complete SSE Event Translation

Azure and Codex stream Responses-style SSE events. The proxy converts provider SSE back to OpenAI Chat Completions chunks for Cursor, and the Azure adapter handles the broad Azure event surface:

- **Reasoning:** `reasoning_text.delta`, `reasoning_summary_text.delta` — streamed inside `<think>` tags
- **Text:** `output_text.delta` — standard content streaming
- **Tool calls:** `function_call.arguments.delta`, `custom_tool_call_input.delta` — incremental argument streaming
- **Native Azure tools:** `apply_patch_call`, `shell_call`, `local_shell_call`, `mcp_call`, `computer_call` — converted to standard function calls Cursor understands
- **Errors:** `response.failed`, `response.incomplete`, `error` — surfaced with context
- **Refusals:** `refusal.delta` — model refusal text passed through
- **Audio:** `audio.delta`, `audio.transcript.delta`
- **Code interpreter:** `code_interpreter_call_code.delta`
- **Lifecycle events** (created, queued, in_progress, done) — silently skipped
- **Unknown events** — logged, never silently dropped

### Dual Input Format Support

The proxy accepts both request formats Cursor may send:

- **Chat Completions** (`messages` array) — converted to Responses API format
- **Responses API** (`input` + `instructions`) — passed through natively

System and developer messages become `instructions`. User/assistant messages become `input` items. Tool results become `function_call_output`. The conversion preserves multimodal content, tool call IDs, and function schemas.

### Native Azure Tool Type Bridging

When Azure returns native tool types that Cursor doesn't understand natively, the proxy wraps them as standard function calls:

| Azure Native Type | Wrapped As | Arguments |
|---|---|---|
| `apply_patch_call` | `ApplyPatch` | `{diff, path}` |
| `shell_call` / `local_shell_call` | `Shell` | `{command, working_directory}` |
| `mcp_call` | `CallMcpTool` | `{server_label, tool_name, arguments}` |
| `computer_call` | `ComputerUse` | `{}` |

### Token Usage and Cost Tracking

Provider usage metadata is mapped back to OpenAI Chat Completions format when it is available:

- `prompt_tokens` (including cached)
- `completion_tokens`
- `total_tokens`
- `prompt_tokens_details.cached_tokens`
- `completion_tokens_details.reasoning_tokens`

Terminal logs show per-request usage with cache hit percentage:

```
USAGE: input=45230 (cached=38400, 85%) output=1205 (reasoning=890) total=46435
```

The included `scripts/analyze_token_usage.py` parses Docker logs and produces a full report with percentiles, cost estimates, and the largest requests:

```bash
python scripts/analyze_token_usage.py --hours 48
```

### Rich Terminal Logging

Requests are pretty-printed with [Rich](https://github.com/Textualize/rich): color-coded message roles, tool parameter tables, streaming live panels showing the response as it builds, and structured error output. Sensitive values (API keys, auth headers) are redacted by default.

---

## Supported Models

Azure and Codex model lists are separate. Root and `/azure` expose Azure models. `/codex` exposes the Codex/ChatGPT subscription model list from `CODEX_SUPPORTED_MODELS`.

The Azure provider accepts these Cursor-facing model IDs in parallel. Configure one Azure deployment per model you want to use, then select among them directly in Cursor's built-in model picker — no legacy alias swapping or separate proxy instances required.

| Model | Status |
|---|---|
| `gpt-5.5` | Verified |
| `gpt-5.4` | Verified |
| `gpt-5.4-mini` | Verified |
| `gpt-5.4-nano` | Verified |
| `gpt-5.3-codex` | Verified |
| `gpt-5.2` | Expected to work (same Responses API) |
| `gpt-5.2-codex` | Verified |
| `gpt-5.1` | Expected to work (same Responses API) |
| `gpt-5.1-codex` | Expected to work (same Responses API) |
| `gpt-5.1-codex-max` | Expected to work (same Responses API) |
| `gpt-5.1-codex-mini` | Verified |
| `gpt-5` | Expected to work (same Responses API) |
| `gpt-5-mini` | Verified |
| `gpt-5-codex` | Expected to work (same Responses API) |

**Verified** = manually tested end-to-end with a real Cursor client through the proxy to Azure. **Expected to work** = these models use the same Azure Responses API surface, but have not been individually verified. If you test one and it works (or doesn't), please [open an issue](https://github.com/gabrii/Cursor-Azure-GPT-5/issues) so we can update this table.

The Codex provider defaults to:

```env
CODEX_SUPPORTED_MODELS=gpt-5.5,gpt-5.4,gpt-5.4-mini,gpt-5.3-codex,gpt-5.3-codex-spark
```

That list is intentionally configurable because Codex/ChatGPT subscription availability can differ by account and over time.

The Codex provider has also been tested end-to-end with real Cursor agent traffic through `/codex/chat/completions`, including tool calls, subagents, MCP browser calls, shell calls, patch application, streaming usage chunks, and the temporary `gpt-5.4:gpt-5.5` rewrite path.

Legacy aliases (`gpt-high`, `gpt-medium`, `gpt-low`, `gpt-minimal`) are **intentionally not supported**. Use Cursor's native model picker and thinking controls instead — the proxy forwards `reasoning.effort` directly.

---

## Provider Paths

Azure and Codex are peers. The only reason Azure owns the root path is backward compatibility with existing deployments. The same public host can expose one or both providers:

| Cursor Override Base URL | Provider | Model list |
|---|---|---|
| `https://your-public-proxy-url` | Azure | Azure models |
| `https://your-public-proxy-url/azure` | Azure | Azure models |
| `https://your-public-proxy-url/codex` | Codex | Codex models |

Root is always Azure. It never falls through to Codex. Switching a Cursor client from Azure to the ChatGPT subscription-backed Codex provider only requires changing the provider word in the base URL from `/azure` to `/codex`; the OpenAI API key remains the same `SERVICE_API_KEY`.

### GPT-5.5 Cursor Routing Issue

Cursor may currently fail to route direct `gpt-5.5` custom-base-url traffic to this proxy and instead return `User API Key Rate limit exceeded`.

Until Cursor routes native `gpt-5.5` custom URLs correctly, Codex users can use an explicit temporary rewrite:

```env
CODEX_MODEL_REWRITES=gpt-5.4:gpt-5.5
```

With that setting, configure Cursor to send `gpt-5.4` through the `/codex` custom base URL and the proxy rewrites only the upstream `model` field to `gpt-5.5`.

Azure users can use the deployment mapping mechanism for the same workaround:

```env
AZURE_MODEL_DEPLOYMENTS={"gpt-5.4":"your-gpt-5.5-deployment-name"}
```

With that setting, configure Cursor to send `gpt-5.4` through the Azure/root custom base URL and the proxy sends the request to your configured `gpt-5.5` Azure deployment.

Both workarounds are stopgaps, not native `gpt-5.5` support. Cursor still builds the prompt, tool setup, reasoning defaults, and session identity for the source model (`gpt-5.4` in these examples), so there is prompt/model skew. We do not know exactly whether Cursor's `gpt-5.4` and `gpt-5.5` prompts differ or by how much, so performance and behavior may not be identical to native `gpt-5.5` routing. Remove these workarounds when Cursor can route `gpt-5.5` directly.

---

## Quick Start

### 1. Configure

```bash
cp .env.example .env
```

Edit `.env` for the provider you want to use. For Codex/ChatGPT subscription:

```env
SERVICE_API_KEY=choose-a-local-secret
ENABLE_AZURE=false
ENABLE_CODEX=true
CODEX_AUTH_PATH=~/.codex/auth.json
CODEX_SUPPORTED_MODELS=gpt-5.5,gpt-5.4,gpt-5.4-mini,gpt-5.3-codex,gpt-5.3-codex-spark
```

Run `codex login` on the machine hosting the proxy before starting the service.

For Azure:

```env
SERVICE_API_KEY=choose-a-local-secret
ENABLE_AZURE=true
ENABLE_CODEX=false
AZURE_BASE_URL=https://your-resource.openai.azure.com
AZURE_API_KEY=your-azure-api-key
```

`AZURE_BASE_URL` is the Azure OpenAI resource root. Do **not** append `/openai/v1` or `/openai/responses` — the proxy builds the full Azure v1 Responses URL itself.

### 2. Start

```bash
./start.sh 8082
```

This creates a virtualenv if needed, installs dependencies, and starts Flask on `http://localhost:8082`.

### 3. Expose

Cursor's servers must reach the proxy. Use a reverse proxy, exposed domain, or tunnel:

```bash
# Example: Cloudflare Tunnel
cloudflared tunnel --url http://localhost:8082
```

### 4. Configure Cursor

```
Settings > Models > OpenAI API Key    →  the SERVICE_API_KEY from .env
Settings > Models > Override Base URL →  https://your-public-proxy-url
```

Then select models normally in Cursor (e.g. `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, Codex variants). Multiple mapped Azure deployments and Codex subscription models can be available side-by-side on the same host; you switch provider by changing the base URL path. Cursor also keeps using its built-in model-specific prompts automatically.

### Azure-Only Setup

Use the default provider switches:

```env
ENABLE_AZURE=true
ENABLE_CODEX=false
```

Set Cursor's override base URL to `https://your-public-proxy-url` or `https://your-public-proxy-url/azure`.

### Codex-Only Setup

Run `codex login` first so `~/.codex/auth.json` contains ChatGPT auth state from the account that has the monthly subscription you want to use, then configure:

```env
ENABLE_AZURE=false
ENABLE_CODEX=true
CODEX_AUTH_PATH=~/.codex/auth.json
CODEX_SUPPORTED_MODELS=gpt-5.5,gpt-5.4,gpt-5.4-mini,gpt-5.3-codex,gpt-5.3-codex-spark
```

Set Cursor's override base URL to `https://your-public-proxy-url/codex`.

For the current `gpt-5.5` Cursor routing limitation, add:

```env
CODEX_MODEL_REWRITES=gpt-5.4:gpt-5.5
```

Then select `gpt-5.4` in Cursor and keep thinking effort at `low` / `medium` / `high` as usual. Cursor still builds the request as `gpt-5.4`, but the proxy rewrites only the upstream Codex model field to `gpt-5.5`.

### Both Providers On One Host

```env
ENABLE_AZURE=true
ENABLE_CODEX=true
```

Use `https://your-public-proxy-url/azure` for Azure clients and `https://your-public-proxy-url/codex` for Codex clients. Both use the same `SERVICE_API_KEY`.

---

## Configuration

### Required

| Variable | Description |
|---|---|
| `SERVICE_API_KEY` | Secret the proxy validates against Cursor's `OpenAI API Key` setting |
| `AZURE_BASE_URL` | Azure OpenAI resource URL when Azure is enabled |
| `AZURE_API_KEY` | Azure OpenAI API key when Azure is enabled |
| `CODEX_AUTH_PATH` | Codex ChatGPT auth file when Codex is enabled |

### Optional

| Variable | Default | Description |
|---|---|---|
| `ENABLE_AZURE` | `true` | Enable the root and `/azure` provider |
| `ENABLE_CODEX` | `false` | Enable the `/codex` provider |
| `AZURE_MODEL_DEPLOYMENTS` | Identity map | JSON mapping from Cursor model IDs to Azure deployment names |
| `AZURE_SUMMARY_LEVEL` | `detailed` | Reasoning summary: `auto`, `detailed`, or `concise` |
| `AZURE_VERBOSITY_LEVEL` | `medium` | Text verbosity: `low`, `medium`, or `high` |
| `AZURE_TRUNCATION` | `disabled` | Truncation mode: `auto` or `disabled` |
| `CODEX_RESPONSES_URL` | ChatGPT Codex backend URL | Codex Responses endpoint used by ChatGPT subscription auth |
| `CODEX_SUPPORTED_MODELS` | Codex default list | Comma-separated Codex/ChatGPT subscription model list exposed at `/codex/v1/models` |
| `CODEX_MODEL_REWRITES` | Empty | Comma-separated `source:target` rewrites for temporary routing workarounds |
| `CODEX_ORIGINATOR` | `codex_cli_rs` | Codex upstream originator header |
| `CODEX_USER_AGENT` | Codex proxy UA | Codex upstream user-agent header |
| `CODEX_DISCOVERY_MODE` | `false` | Allows first captures without Cursor markers |
| `CODEX_TOKEN_REFRESH_SKEW_SECONDS` | `300` | Refresh access tokens before expiry |
| `CODEX_REQUEST_TIMEOUT_SECONDS` | `600` | Codex upstream read timeout |
| `RECORD_TRAFFIC` | `off` | Write redacted request/response fixtures to `recordings/` |
| `LOG_CONTEXT` | `off` | Log incoming request details. Enable only for debugging because Cursor agent requests can contain very large prompts and tool transcripts |
| `LOG_COMPLETION` | `on` | Log streamed completion content |
| `LOG_REDACT` | `true` | Redact API keys and sensitive values in logs |

### Deployment Mapping

If your Azure deployment names match the Cursor model IDs, leave `AZURE_MODEL_DEPLOYMENTS` empty. Otherwise, map each Cursor model ID to the Azure deployment that should serve it:

```env
AZURE_MODEL_DEPLOYMENTS={"gpt-5.5":"prod-gpt55","gpt-5.4":"prod-gpt54","gpt-5.4-mini":"team-mini"}
```

Cursor still sees the native IDs (`gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`) and can switch between them normally. Azure receives the matching deployment name for the selected model.

---

## Running

### Local (recommended for development)

```bash
./start.sh 8082
```

### Manual Flask

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements/dev.txt
FLASK_APP=autoapp.py flask run -p 8082
```

### Docker (production)

```bash
docker compose up flask
```

Runs gunicorn + supervisord behind port `127.0.0.1:5000` with health checks every 10s.

When Codex is enabled, `docker-compose.yml` mounts the host user's `~/.codex` directory into the container at `/home/sid/.codex` so ChatGPT auth state is available inside Docker:

```yaml
volumes:
  - "${HOME}/.codex:/home/sid/.codex"
```

This is intentionally generic for repo users:
- run `codex login` on the same machine that will run Docker
- keep `CODEX_AUTH_PATH=~/.codex/auth.json`
- do not mount the directory read-only, because Codex token refresh may replace `auth.json`
- do not run multiple independent Codex proxies or copied `auth.json` files against the same login state at the same time

`/codex/ready` checks that the auth file is readable and that its parent directory is writable for token refresh.

Codex refresh follows the Codex CLI pattern: the proxy uses the ChatGPT refresh token from `auth.json`, calls OpenAI's auth refresh endpoint, stores the returned access/refresh tokens back into `auth.json`, and retries once if the Codex backend rejects an access token with `401`.

Codex refresh tokens are single-use. This proxy serializes refresh attempts across local workers with a file lock before replacing `auth.json`, but it cannot coordinate with another machine, another copied auth file, or an independently running Codex process that refreshes the same login state. If Codex auth starts failing after sharing or copying `auth.json`, run `codex login` again on the host that owns the proxy.

### Docker (development)

```bash
docker compose --profile dev up flask-dev
```

Runs Flask dev server on port `8082` with volume mounts for live reload.

---

## Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | No | Health check |
| `GET` | `/v1/models` | Bearer | List Azure models |
| `GET` | `/azure/v1/models` | Bearer | List Azure models |
| `GET` | `/codex/v1/models` | Bearer | List Codex/ChatGPT subscription models |
| `GET` | `/codex/ready` | Bearer | Validate Codex auth state |
| `POST` | `/v1/chat/completions` | Bearer | Chat completions forwarded to Azure |
| `POST` | `/azure/v1/chat/completions` | Bearer | Chat completions forwarded to Azure |
| `POST` | `/codex/v1/chat/completions` | Bearer | Chat completions forwarded to Codex |
| `POST` | `/v1/responses` | Bearer | Responses API forwarded to Azure |
| `POST` | `/azure/v1/responses` | Bearer | Responses API forwarded to Azure |
| `POST` | `/codex/v1/responses` | Bearer | Responses API forwarded to Codex |
| `*` | `/*` | Bearer | Catch-all proxy |

---

## Smoke Tests

```bash
# Health check (no auth)
curl http://127.0.0.1:8082/health

# Model list (requires auth)
curl -H "Authorization: Bearer $SERVICE_API_KEY" \
  http://127.0.0.1:8082/v1/models

# Codex readiness and model list, when ENABLE_CODEX=true
curl -H "Authorization: Bearer $SERVICE_API_KEY" \
  http://127.0.0.1:8082/codex/ready
curl -H "Authorization: Bearer $SERVICE_API_KEY" \
  http://127.0.0.1:8082/codex/v1/models
```

---

## Architecture

```
Cursor ──► Proxy ─┬─► Azure OpenAI        / and /azure
                  └─► Codex/ChatGPT      /codex
           │
           ├── blueprint.py          Provider routing & auth
           ├── azure/
           │   ├── adapter.py        Orchestrator
           │   ├── request_adapter.py Chat → Responses format
           │   └── response_adapter.py Azure SSE → Chat SSE
           ├── codex/
           │   ├── adapter.py        Flask Codex provider
           │   ├── auth_state.py     Codex ChatGPT auth handling
           │   ├── request_adapter.py Cursor → Codex Responses format
           │   ├── response_adapter.py Codex SSE → Chat SSE
           │   └── upstream.py       Codex headers & request
           ├── models.py             Model list & deployment map
           ├── settings.py           Env config
           ├── auth.py               Bearer token validation
           └── common/
               ├── sse.py            SSE encode/decode
               ├── logging.py        Rich logging
               ├── recording.py      Traffic recording
               └── token_usage_report.py  Usage analysis
```

**Request flow:**

1. Cursor sends POST to proxy (Chat Completions or Responses format)
2. `blueprint.py` selects Azure for root or `/azure`, Codex for `/codex`
3. The provider request adapter transforms to its Responses API format
4. `requests` forwards upstream
5. The provider response adapter converts SSE events to Chat Completions chunks when Cursor used Chat Completions
6. Flask streams the converted response back to Cursor

---

## Development

### Tests

```bash
flask test           # pytest with coverage
flask test -k "cache"  # filter by keyword
```

The test suite includes unit tests, configuration validation, request/response adapter tests, error handling, and replay tests using recorded SSE fixtures.

### Lint

```bash
flask lint           # format with black + isort, check with flake8
flask lint --check   # check only, no modifications
```

### CI

GitHub Actions runs lint + tests on every push with Python 3.13 and uploads coverage to Codecov.

---

## Traffic Recording

Set `RECORD_TRAFFIC=on` to write redacted request/response pairs to `recordings/`. Each request lifecycle gets a numbered subdirectory:

```
recordings/
  1/
    downstream_request.json    # What Cursor sent
    upstream_request.json      # What we sent upstream
    upstream_response.sse      # Upstream raw SSE stream
    downstream_response.sse    # What we sent back to Cursor
```

Sensitive data (content, instructions, user IDs, function names) is automatically anonymized. Useful for debugging and building test fixtures.

---

## Troubleshooting

**`401` / `403` from Azure**
Check `AZURE_API_KEY`, the Azure resource, and whether the deployment exists.

**`404` from Azure**
Check `AZURE_BASE_URL` (should be the resource root, not a full path) and `AZURE_MODEL_DEPLOYMENTS` (deployment name must exist in Azure).

**Cursor cannot connect**
The override base URL must be reachable from outside your machine. `http://localhost:8082` only works for local health checks. Use a tunnel or reverse proxy for the public URL.

**Docker + Codex returns `not_ready`**
Check the Codex auth mount inside the container. The common working pattern is mounting `${HOME}/.codex` to `/home/sid/.codex` with write access so refreshed tokens can replace `auth.json`.

**Auth mismatch**
The proxy returns a clear error: the `OpenAI API Key` in Cursor settings must exactly match `SERVICE_API_KEY` in `.env`.

**Codex is not ready**
Run `codex login` on the machine hosting the proxy, confirm `CODEX_AUTH_PATH` points at that auth file, and check `/codex/ready` with the shared bearer secret. A healthy response is `{"status":"ready"}`.

**Codex refresh token was already used**
Refresh tokens are single-use. Avoid running multiple proxy instances or copied `auth.json` files from the same login state. Run `codex login` again on the proxy host, then restart the service.

**Codex direct curl tests fail with `Missing Cursor Request Marker`**
The Codex adapter rejects requests that look non-Cursor unless it can derive a session identity. With `CODEX_DISCOVERY_MODE=false` (the default), satisfy **any one** of:

- JSON field `"user": "<stable-string-per-chat>"` on the request body, or
- `metadata` with `cursorConversationId` / `conversation_id` / `thread_id` / `session_id`, or
- Headers such as `x-cursor-conversation-id` or `x-client-request-id`, or
- Any header whose name or value contains `cursor` (case-insensitive)

If a Cursor surface you use sometimes omits all of the above, set `CODEX_DISCOVERY_MODE=true` in `.env` and restart the proxy. That relaxes marker validation for easier integration at the cost of accepting more generic traffic.

Example manual curl with a marker header:

```bash
curl -N \
  -H "Authorization: Bearer $SERVICE_API_KEY" \
  -H "Content-Type: application/json" \
  -H "x-client-request-id: debug-codex-1" \
  http://127.0.0.1:8082/codex/v1/chat/completions \
  -d '{"model":"gpt-5.4","messages":[{"role":"user","content":"Reply with exactly: hello"}]}'
```

**Codex model does not appear**
Check `CODEX_SUPPORTED_MODELS`. `/codex/v1/models` is intentionally separate from `/v1/models` and `/azure/v1/models`.
