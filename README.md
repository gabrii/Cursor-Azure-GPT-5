# Cursor Azure GPT-5

[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=fff)](#)
[![Flask](https://img.shields.io/badge/Flask-009485?logo=flask&logoColor=fff)](#)
[![Pytest](https://img.shields.io/badge/Pytest-fff?logo=pytest&logoColor=000)](#)
[![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=fff)](#)

This project is a proxy that lets Cursor use Azure OpenAI GPT-5 deployments even when Cursor itself expects an OpenAI-style `/chat/completions` endpoint.

In practice, the proxy sits between Cursor and Azure and does three jobs:

- it accepts Cursor-compatible chat completion requests
- it converts them into Azure Responses API requests
- it converts Azure's streamed responses back into the completion chunks Cursor expects

That means you can keep using Cursor as usual, while hosting the actual models in Azure.

> [!WARNING]
> You still need an active paid Cursor subscription to use this project.

## Why this fork exists

This fork keeps the original idea, but tightens it around what actually works well for an Azure-based Cursor setup today.

The main changes in this fork are:

- only real bare Cursor model ids are accepted, such as `gpt-5.4`, `gpt-5.4-mini`, and `gpt-5.3-codex`
- old alias models like `gpt-high`, `gpt-medium`, `gpt-low`, and `gpt-minimal` are removed instead of being kept as compatibility baggage
- Cursor's own native `reasoning.effort` payload is forwarded directly, so thinking level comes from Cursor's UI rather than model-name tricks
- Azure deployment names can be configured independently from the public model ids Cursor sees
- replay tests and request fixtures are aligned to the cleaned model contract
- token-usage analysis tooling is included for inspecting real proxy usage from logs

If your goal is "make Cursor talk to Azure GPT-5 cleanly, with less legacy weirdness," this fork is aimed at that.

## Supported model ids

The proxy accepts these Cursor-facing model ids:

- `gpt-5`
- `gpt-5-mini`
- `gpt-5-codex`
- `gpt-5.1`
- `gpt-5.1-codex`
- `gpt-5.1-codex-max`
- `gpt-5.1-codex-mini`
- `gpt-5.2`
- `gpt-5.2-codex`
- `gpt-5.3-codex`
- `gpt-5.4`
- `gpt-5.4-mini`
- `gpt-5.4-nano`

Legacy alias names such as `gpt-high`, `gpt-medium`, `gpt-low`, and `gpt-minimal` are intentionally **not** supported.

## How model selection works

There are two names involved in every request:

1. The public model id that Cursor sends to the proxy, for example `gpt-5.4`
2. The Azure deployment name that your Azure resource actually exposes, for example `my-company-gpt54-prod`

By default, this proxy assumes those names are the same.

If your Azure deployment names are different, set `AZURE_MODEL_DEPLOYMENTS` to a JSON object that maps Cursor-facing ids to Azure deployment names.

Example:

```json
{
  "gpt-5.4": "my-company-gpt54-prod",
  "gpt-5.4-mini": "my-team-mini",
  "gpt-5.3-codex": "codex-eastus"
}
```

This is one of the most important differences from the older setup: you no longer need to rename models or invent alias ids just to target a deployment.

## Quick start

If you only want a working setup quickly, this is the shortest path.

### 1. Create your config

Copy `.env.example` to `.env`.

Required values:

| Flag | Description | Default |
| --- | --- | --- |
| `SERVICE_API_KEY` | The secret Cursor will use as its OpenAI API key when calling this proxy. | `change-me` |
| `AZURE_BASE_URL` | Your Azure OpenAI base URL, without a trailing slash. | required |
| `AZURE_API_KEY` | Your Azure OpenAI API key. | required |

Optional but often useful:

| Flag | Description | Default |
| --- | --- | --- |
| `AZURE_MODEL_DEPLOYMENTS` | JSON mapping from public model ids to Azure deployment names. Leave empty if names already match. | empty |
| `AZURE_API_VERSION` | Azure Responses API version to call. | `2025-04-01-preview` |
| `AZURE_SUMMARY_LEVEL` | Default reasoning summary hint sent upstream. | `detailed` |
| `AZURE_VERBOSITY_LEVEL` | Default verbosity hint sent upstream. | `medium` |
| `AZURE_TRUNCATION` | Default truncation mode sent upstream. | `disabled` |
| `RECORD_TRAFFIC` | Write redacted request/response fixtures to disk. | `off` |
| `LOG_CONTEXT` | Pretty-print request context in the terminal. | `on` |
| `LOG_COMPLETION` | Log completion payloads. | `on` |

### 2. Start the proxy

You have three common ways to run it.

#### Option A: simple local helper

```bash
./start.sh 8082
```

This is the easiest local entrypoint. It creates `.venv` if needed, prints the important Cursor values, and runs the Flask app on the port you choose.

#### Option B: Docker production-style run

```bash
docker compose up flask
```

This runs the production image with `supervisord` and `gunicorn`.

#### Option C: Docker dev workflow

```bash
docker compose --profile dev up flask-dev
```

This runs the development image with the repo mounted in, which is more convenient while editing code.

### 3. Expose it to Cursor

Cursor needs a publicly reachable base URL. A quick option is `cloudflared`:

```bash
cloudflared tunnel --url http://localhost:8082
```

This gives you a public HTTPS URL that forwards to your local proxy.

### 4. Configure Cursor

In Cursor, set:

1. `Override OpenAI Base URL` -> your public proxy URL
2. `OpenAI API Key` -> the `SERVICE_API_KEY` from `.env`
3. Add whichever supported model ids you want Cursor to use, such as `gpt-5.4`, `gpt-5.4-mini`, or `gpt-5.3-codex`

Important behavior change versus older setups:

- do **not** create one model per reasoning level
- do **not** use `gpt-high` / `gpt-low` style aliases
- do use Cursor's built-in thinking controls, because the proxy forwards `reasoning.effort` natively

## User-friendly setup examples

### Example 1: deployment names already match

If your Azure deployments are literally named `gpt-5.4` and `gpt-5.4-mini`, your `.env` can stay simple:

```env
SERVICE_API_KEY=replace-me
AZURE_BASE_URL=https://your-resource.openai.azure.com
AZURE_API_KEY=replace-me
AZURE_MODEL_DEPLOYMENTS=
```

### Example 2: deployment names are custom

If Azure uses different deployment names, map them explicitly:

```env
SERVICE_API_KEY=replace-me
AZURE_BASE_URL=https://your-resource.openai.azure.com
AZURE_API_KEY=replace-me
AZURE_MODEL_DEPLOYMENTS={"gpt-5.4":"prod-gpt54","gpt-5.4-mini":"mini-westus","gpt-5.3-codex":"codex-prod"}
```

Cursor still sees `gpt-5.4`, `gpt-5.4-mini`, and `gpt-5.3-codex`. Only Azure sees the custom deployment names.

## Feature highlights

- Native forwarding of Cursor `reasoning.effort`
- Configurable Azure deployment mapping per model id
- Prompt caching that works well in practice for long Cursor conversations
- Rich request/context logging in the terminal
- Replay-style test fixtures under `tests/recordings/`
- Azure error responses cleaned up for easier debugging
- Token-usage reporting from Docker logs

## Prompt caching

Prompt caching works really well with this proxy when Cursor stays within the
same conversation.

That matters a lot for real agent usage, where prompts can become very large
after many tool calls and long context chains. Without stable cache routing,
Azure can keep sending related requests to different backend machines, which
means each machine sees a cold cache and you lose most of the benefit.

This proxy intentionally follows the same basic caching strategy used by Codex
CLI-style clients:

- it derives a per-conversation id from Cursor's `metadata.cursorConversationId`
- it sends that id as `session_id` and `x-client-request-id` headers
- it uses that same id as `prompt_cache_key`
- it sets `store=true` so Azure can reuse prior conversation state for caching
- it keeps tool-call behavior aligned with the same flow by sending `parallel_tool_calls=true`

The important detail is that cache routing is tied to the conversation id, not
to Cursor's `user` field. The `user` field is stable across conversations, so
using it for cache affinity can cause collisions and weaker cache behavior when
multiple sessions are active.

The proxy also surfaces cache information back to you:

- Azure usage chunks forwarded to Cursor include cached token counts
- terminal logs print `USAGE:` lines with cached-token totals and cache-hit percentage
- `scripts/analyze_token_usage.py` can summarize those logs over time

So the fork is not just "cache-compatible" on paper. It is set up to preserve
cache affinity across turns and to make cache performance visible when you want
to measure whether it is paying off.

## Token usage analysis

This fork includes a small utility for summarizing real token usage from proxy logs.

Code lives in:

- `app/common/token_usage_report.py`
- `scripts/analyze_token_usage.py`

Example:

```bash
python scripts/analyze_token_usage.py --hours 48
```

That reads Docker Compose logs from the `flask` service, parses `USAGE:` lines, and prints:

- request counts
- input, cached, output, and reasoning token totals
- cache hit rate
- estimated spend using configurable per-million token prices
- largest requests by input size

This is useful if you want real numbers for cache efficiency, context size, or spend trends without wiring up a full external monitoring stack first.

## Development

### Local Python workflow

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements/dev.txt
flask run -p 8080
```

### Tests

Run everything:

```bash
flask test
```

Run a subset:

```bash
flask test -k request_adapter
```

### Lint

```bash
flask lint
```

Check-only mode:

```bash
flask lint --check
```

### Docker helper commands

Run tests:

```bash
docker compose --profile dev run --rm manage test
```

Run lint:

```bash
docker compose --profile dev run --rm manage lint
```

## Testing fixtures

When `RECORD_TRAFFIC=on`, the proxy writes redacted request and response fixtures under `recordings/`.

Sensitive Cursor scaffolding is stripped out so those fixtures can be committed under `tests/recordings/` and reused as replay tests without exposing private prompt-building details.

## Production notes

The `flask` service in `docker-compose.yml` runs the production image through `supervisord` and `gunicorn`.

Relevant files:

- `supervisord/gunicorn.conf`
- `supervisord/supervisord_entrypoint.sh`
- `supervisord/supervisord.conf`

To build and publish the production image:

```bash
docker compose build flask
docker tag cursor-azure-gpt5 your-tag
docker push your-tag
```