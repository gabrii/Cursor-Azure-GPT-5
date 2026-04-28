# Cursor Azure GPT-5

> **This project is back and actively maintained.** After months of dependency-only updates, the proxy has been overhauled with a complete rewrite of the request/response layer, full Responses API support, prompt caching, native reasoning controls, and much more. It is being used daily in production with Cursor. **If you run into issues, please [open an issue](https://github.com/gabrii/Cursor-Azure-GPT-5/issues)** — bug reports and feedback are essential to keep this working well for everyone.

A Flask proxy that lets **Cursor** use **Azure OpenAI** deployments as if they were native OpenAI models — with full support for streaming, reasoning, tool calls, and prompt caching.

Cursor sends standard OpenAI requests. This proxy translates them to Azure's Responses API on the fly, then streams back responses in the exact format Cursor expects. No Cursor modifications needed, no forks — just point and go.

> **You still need a paid Cursor plan.** This project only redirects where model traffic goes.

---

## Why This Exists

Cursor talks OpenAI. Azure talks Responses API. The two formats differ in request structure, streaming event types, tool call schemas, and usage reporting. This proxy sits in the middle and handles the full translation — both directions, in real time, while streaming.

It was built to get **full Cursor feature parity** on Azure, including things most simple proxies break: reasoning effort controls, extended thinking with `<think>` tags, parallel tool calls, native Azure tool types (shell, patch, MCP), and prompt caching with per-conversation cache affinity.

---

## Key Features

### Native Multi-Model Selection (No Legacy Aliases)

Unlike older proxy setups that forced you into one deployment or generic aliases like `gpt-high` / `gpt-medium`, this proxy exposes many Cursor-native models at the same time. You can keep `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, Codex variants, and other supported IDs available in Cursor's built-in model picker, then switch between them per chat exactly like you would with Cursor's default model selection.

The proxy uses Cursor's **real model IDs** (e.g. `gpt-5.4`, `gpt-5.4-mini`). This means **Cursor sends its tailored, model-specific system prompts** rather than generic fallbacks — resulting in noticeably better output quality, because each model gets the prompt engineering Cursor designed for it.

The proxy preserves Cursor's native `reasoning.effort` field and forwards it directly to Azure, so Cursor's thinking controls (low / medium / high) work exactly as intended.

### Prompt Caching with Per-Conversation Affinity

The proxy extracts `metadata.cursorConversationId` from each request and uses it as the cache routing key. For every conversation it sets:

- `prompt_cache_key` = conversation ID
- `session_id` = conversation ID (pins requests to the same Azure backend machine)
- `x-client-request-id` = conversation ID (per-conversation request correlation)
- `store: true` (enables Azure server-side storage for 24h cache retention)
- `parallel_tool_calls: true`

This means long Cursor conversations reuse their prompt cache across turns, significantly reducing input token costs and latency. The proxy logs cache hit rates per request (`USAGE:` lines) and includes `prompt_tokens_details.cached_tokens` in the response so Cursor can display cache statistics.

In real Cursor agent sessions, mature conversations regularly hit the practical ceiling for prompt caching — often **99%+ cached input tokens** once the stable context is warm. Parallel tool calls, subagents, and multiple concurrent agent flows can run without throwing away the cache, because each conversation keeps its own cache key and Azure backend affinity instead of sharing one global user bucket.

> **Why this matters:** The `user` field is a per-user hash shared across all conversations — using it for cache routing would mix unrelated conversations on the same cache partition. This proxy explicitly routes by conversation ID instead.

### Complete SSE Event Translation

Azure's Responses API emits 53+ different SSE event types. The proxy handles all of them:

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

Every response includes full usage metadata in OpenAI Chat Completions format:

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

The proxy accepts these Cursor-facing model IDs in parallel. Configure one Azure deployment per model you want to use, then select among them directly in Cursor's built-in model picker — no legacy alias swapping or separate proxy instances required.

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

Legacy aliases (`gpt-high`, `gpt-medium`, `gpt-low`, `gpt-minimal`) are **intentionally not supported**. Use Cursor's native model picker and thinking controls instead — the proxy forwards `reasoning.effort` directly.

---

## Quick Start

### 1. Configure

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
SERVICE_API_KEY=choose-a-local-secret
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

Then select models normally in Cursor (e.g. `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, Codex variants). Multiple mapped Azure deployments can be available side-by-side through Cursor's built-in model picker; you no longer need the old one-model-at-a-time alias workflow. Cursor also keeps using its built-in model-specific prompts automatically.

---

## Configuration

### Required

| Variable | Description |
|---|---|
| `SERVICE_API_KEY` | Secret the proxy validates against Cursor's `OpenAI API Key` setting |
| `AZURE_BASE_URL` | Azure OpenAI resource URL (e.g. `https://name.openai.azure.com`) |
| `AZURE_API_KEY` | Azure OpenAI API key |

### Optional

| Variable | Default | Description |
|---|---|---|
| `AZURE_MODEL_DEPLOYMENTS` | Identity map | JSON mapping from Cursor model IDs to Azure deployment names |
| `AZURE_SUMMARY_LEVEL` | `detailed` | Reasoning summary: `auto`, `detailed`, or `concise` |
| `AZURE_VERBOSITY_LEVEL` | `medium` | Text verbosity: `low`, `medium`, or `high` |
| `AZURE_TRUNCATION` | `disabled` | Truncation mode: `auto` or `disabled` |
| `RECORD_TRAFFIC` | `off` | Write redacted request/response fixtures to `recordings/` |
| `LOG_CONTEXT` | `on` | Log incoming request details |
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
| `GET` | `/v1/models` | Bearer | List supported models |
| `POST` | `/v1/chat/completions` | Bearer | Chat completions (forwarded to Azure) |
| `POST` | `/openai/responses` | Bearer | Responses API (forwarded to Azure) |
| `*` | `/*` | Bearer | Catch-all proxy |

---

## Smoke Tests

```bash
# Health check (no auth)
curl http://127.0.0.1:8082/health

# Model list (requires auth)
curl -H "Authorization: Bearer $SERVICE_API_KEY" \
  http://127.0.0.1:8082/v1/models
```

---

## Architecture

```
Cursor ──► Proxy ──► Azure OpenAI
           │
           ├── blueprint.py          Routes & auth
           ├── azure/
           │   ├── adapter.py        Orchestrator
           │   ├── request_adapter.py Chat → Responses format
           │   └── response_adapter.py Azure SSE → Chat SSE
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
2. `RequestAdapter` transforms to Azure Responses API format, sets cache headers
3. `requests.request()` streams from Azure
4. `ResponseAdapter` converts each Azure SSE event to a Chat Completions chunk
5. Flask streams the converted response back to Cursor

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
    upstream_request.json      # What we sent to Azure
    upstream_response.sse      # Azure's raw SSE stream
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

**Auth mismatch**
The proxy returns a clear error: the `OpenAI API Key` in Cursor settings must exactly match `SERVICE_API_KEY` in `.env`.

