# Temporary Codex Model Rewrites

## Status

Accepted as a temporary workaround.

## Context

Cursor may not reliably route direct `gpt-5.5` traffic to a custom OpenAI-compatible base URL. In that failure mode, Cursor can return `User API Key Rate limit exceeded` before traffic reaches the proxy.

## Decision

Expose `CODEX_MODEL_REWRITES` for the Codex provider. The format is comma-separated `source:target` entries, for example:

```env
CODEX_MODEL_REWRITES=gpt-5.4:gpt-5.5
```

The rewrite is applied after the downstream model is validated and changes only the upstream `model` field.

## Consequences

This lets users send Cursor `gpt-5.4` traffic through `/codex` while asking the Codex backend for `gpt-5.5`. It is not equivalent to native Cursor `gpt-5.5` routing because Cursor still builds prompts, tools, reasoning settings, and session identity for the source model.

The workaround should be removed when Cursor routes native `gpt-5.5` custom URL traffic correctly.
