# Cursor Azure GPT-5

A small Flask proxy that lets Cursor talk to Azure OpenAI GPT-5 deployments.

Cursor sends OpenAI-compatible requests to this service. The proxy adapts those
requests to Azure's Responses API, forwards them to your Azure deployment, then
streams the response back in the shape Cursor expects.

You still need a paid Cursor plan. This project only changes where Cursor's
model traffic goes.

## What It Does

- Accepts Cursor `/chat/completions`, `/responses`, `/models`, and health-check traffic.
- Converts Cursor chat payloads into Azure Responses API payloads.
- Preserves Cursor's native `reasoning.effort` instead of using legacy model aliases.
- Maps Cursor-facing model ids to Azure deployment names.
- Streams tool calls, reasoning text, errors, usage, and cache metadata back to Cursor.
- Routes prompt caching by Cursor conversation id for better Azure cache affinity.

## Quick Start

Create a local environment file:

```bash
cp .env.example .env
```

Edit `.env` and set at least:

```env
SERVICE_API_KEY=choose-a-local-secret
AZURE_BASE_URL=https://your-resource.openai.azure.com
AZURE_API_KEY=your-azure-api-key
```

`AZURE_BASE_URL` should be the Azure OpenAI resource base URL. For this codebase,
do not include `/openai/v1` or `/openai/responses`; the proxy builds the
Responses URL itself.

Start the proxy locally:

```bash
./start.sh 8082
```

For a quick local smoke test, the service is available at:

```text
http://localhost:8082
```

For real Cursor usage, the override base URL must be reachable by Cursor's
servers. Use an exposed domain, reverse proxy, or a tunnel such as Cloudflare
Tunnel that forwards to `http://localhost:8082`.

In Cursor, configure:

```text
Override OpenAI Base URL: https://your-public-proxy-url
OpenAI API Key:           the SERVICE_API_KEY from .env
```

## Configuration

Required variables:

- `SERVICE_API_KEY`: Local proxy secret. Cursor uses this as its OpenAI API key.
- `AZURE_BASE_URL`: Azure OpenAI resource URL, such as `https://name.openai.azure.com`.
- `AZURE_API_KEY`: Azure OpenAI API key.

Optional variables:

- `AZURE_MODEL_DEPLOYMENTS`: JSON mapping from Cursor model ids to Azure deployment names.
- `AZURE_API_VERSION`: Azure Responses API version. Defaults to `2025-04-01-preview`.
- `AZURE_SUMMARY_LEVEL`: Reasoning summary level. Defaults to `detailed`.
- `AZURE_VERBOSITY_LEVEL`: Text verbosity level. Defaults to `medium`.
- `AZURE_TRUNCATION`: Azure truncation mode. Defaults to `disabled`.
- `RECORD_TRAFFIC`: Write redacted fixtures under `recordings/`. Defaults to `off`.
- `LOG_CONTEXT`: Log request context. Defaults to `on`.
- `LOG_COMPLETION`: Log completion payloads. Defaults to `on`.

If your Azure deployment names match the Cursor model ids, leave
`AZURE_MODEL_DEPLOYMENTS` empty. If not, map only the models you use:

```env
AZURE_MODEL_DEPLOYMENTS={"gpt-5.4":"prod-gpt54","gpt-5.4-mini":"team-mini"}
```

Cursor still sees `gpt-5.4` and `gpt-5.4-mini`; Azure receives your deployment
names.

## Supported Models

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

Legacy aliases such as `gpt-high`, `gpt-medium`, `gpt-low`, and `gpt-minimal`
are intentionally not supported. Use Cursor's thinking controls instead; the
proxy forwards Cursor's native reasoning settings upstream.

## Running It

Local helper:

```bash
./start.sh 8082
```

Manual Flask run:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements/dev.txt
FLASK_APP=autoapp.py flask run -p 8082
```

Production-style Docker run:

```bash
docker compose up flask
```

Development Docker run:

```bash
docker compose --profile dev up flask-dev
```

## Smoke Tests

With the proxy running on port `8082`:

```bash
curl http://127.0.0.1:8082/health
```

Authenticated model list:

```bash
curl -H "Authorization: Bearer $SERVICE_API_KEY" \
  http://127.0.0.1:8082/v1/models
```

The model-list endpoint validates that Cursor can reach the proxy and that
proxy authentication is configured. A real chat request also needs a valid Azure
endpoint, API key, deployment mapping, and a Cursor payload that includes
`reasoning.effort`.

## Prompt Caching

The proxy uses Cursor's `metadata.cursorConversationId` as the cache-routing key.
For each conversation it sets:

- `prompt_cache_key`
- `session_id`
- `x-client-request-id`
- `store: true`
- `parallel_tool_calls: true`

That keeps long Cursor conversations more likely to land on the same Azure cache
partition. Terminal logs also emit `USAGE:` lines with cached-token details, and
`scripts/analyze_token_usage.py` can summarize those logs.

Example:

```bash
python scripts/analyze_token_usage.py --hours 48
```

## Development

Run tests:

```bash
source .venv/bin/activate
pytest -k ""
```

Run lint and formatting:

```bash
source .venv/bin/activate
flask lint
```

Run both before merging changes.

## Troubleshooting

`Environment variable "AZURE_API_VERSION" not set`

Update to a version that includes optional Azure defaults, or set the optional
Azure variables in `.env`. Empty values in `.env.example` are meant to fall back
to defaults.

`401` or `403` from Azure

Check `AZURE_API_KEY`, the Azure resource, and whether the deployment exists in
that resource.

`404` from Azure

Check `AZURE_BASE_URL` and `AZURE_MODEL_DEPLOYMENTS`. The base URL should be the
resource root, and the deployment name sent to Azure must exist.

Cursor cannot connect

Check the URL from outside your machine. Cursor's servers must be able to reach
the override base URL, so use an exposed domain or a Cloudflare Tunnel that
forwards to your local proxy. `http://localhost:8082` is only useful for local
health checks from the machine running this service.
