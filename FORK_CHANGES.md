# Changes Since Forking From `gabrii/Cursor-Azure-GPT-5`

This branch diverged from [`gabrii/Cursor-Azure-GPT-5`](https://github.com/gabrii/Cursor-Azure-GPT-5) at commit `45c5874712f9a05154f4697bfaf056e8535718e1`.

What started as an Azure proxy for Cursor GPT-5 deployments has been shaped into a more opinionated integration: the public model contract is cleaner, Cursor's reasoning controls are forwarded more faithfully, prompt caching is conversation-aware, and the test surface is large enough to protect the fragile parts of the Azure Responses translation layer.

At the time of writing, this branch has 12 unique commits on top of that fork point.

### PR readiness (verified locally)

- **Upstream check:** `https://github.com/gabrii/Cursor-Azure-GPT-5` `HEAD` still resolves to `45c5874712f9a05154f4697bfaf056e8535718e1`, so this fork’s baseline matches current upstream `main` and the diff below is exactly `45c5874..HEAD`.
- **Scope:** 70 files changed, about +3703 / −2002 lines (includes fixture churn in `tests/recordings/`).
- **Tests:** `pytest` — 60 passed (full suite, no skips).

For an upstream PR, point reviewers at this file plus the commit list in [Commit trail since the fork point](#commit-trail-since-the-fork-point). A one-line title idea: *Align Cursor proxy with current models, reasoning forwarding, prompt cache affinity, and usage/replay tooling.*

## How The Fork Evolved

The biggest change is not a single feature, but a shift in how the proxy behaves. Earlier versions were trying to stay broadly compatible with older naming schemes and rougher request shapes. This fork narrowed that down to what actually works cleanly with Cursor today.

Model handling is now explicit and modern. Instead of keeping old alias names around, the proxy accepts the real Cursor-facing ids such as `gpt-5.4`, `gpt-5.4-mini`, and `gpt-5.3-codex`. That removes ambiguity and makes the supported surface easier to reason about when Cursor adds or changes model families.

The reasoning layer was updated in the same spirit. Rather than inferring behavior from model names, the proxy now forwards Cursor's own `reasoning.effort` payload. That means thinking level, verbosity, and summary behavior follow Cursor's UI and request payloads instead of proxy-side heuristics.

Azure request and response translation is where a lot of the heavy lifting happened. The adapters now handle tool payloads more defensively, support `custom_tool_call`, survive invalid JSON, and understand the broad set of Responses API streaming events needed for real Cursor sessions. In practice, that makes the proxy much more tolerant of messy, real-world model output.

Prompt caching was treated as a first-class concern rather than an incidental optimization. Cache routing is now tied to `metadata.cursorConversationId`, with supporting headers and response fields that preserve cache affinity across turns. The result is a more stable conversation cache, better token reuse, and clearer visibility into cache hits and cached-token counts.

Observability got the same treatment. Request logging was cleaned up, Azure errors are reported more clearly, upstream recording no longer crashes the request path, and token usage can now be summarized from logs with a dedicated analysis script. This makes it much easier to understand what the proxy is doing when something goes wrong or when you want to measure cache effectiveness.

Finally, the test story became much stronger. The branch now includes replay fixtures and focused regression coverage for invalid JSON, Azure errors, logging, configuration, model handling, irregular SSE streams, empty tools, and both single and parallel tool-call scenarios. That matters because the proxy sits in a translation layer where small regressions can easily break the whole Cursor-to-Azure flow.

## What Changed, Grouped By Theme

### Model contract and supported behavior

The proxy now reflects the current Cursor model surface instead of preserving old compatibility aliases. That affects `/models`, request validation, and the overall public contract exposed to Cursor.

The reasoning stack was also brought closer to Cursor's actual semantics. Native forwarding for `reasoning.effort`, `minimal` reasoning, summary controls, and safer truncation defaults all reduce the amount of proxy-side interpretation.

### Azure request and response handling

The Azure adapters were expanded to better normalize tool data and to survive the kinds of malformed or partial payloads that real models occasionally emit. That includes non-list tool structures, empty-tools cases, `parallel_tool_calls`, `previous_response_id`, and better handling for streaming events.

Response handling now covers `custom_tool_call`, `response.error`, and the broader SSE event surface expected from Azure Responses API streams. It also fixes context-loss and duplicated closing-tag issues that could make streamed output inconsistent.

### Prompt caching and session affinity

This is one of the most important architectural changes in the fork. Cache routing now follows the actual Cursor conversation id instead of a coarse per-user hash, which means different conversations are less likely to collide and reuse the wrong cache state.

The proxy also forwards `session_id`, `x-client-request-id`, `store=true`, `previous_response_id`, and cache-related token details so Azure can keep the conversation warm and Cursor can see what happened. The cache window was extended to 24 hours to make the optimization useful for longer agent sessions.

### Logging, diagnostics, and usage reporting

The logging path was trimmed down and made more reliable. The branch improves request/context output, removes noisy dead branches, formats Azure errors more clearly, and keeps upstream recording from being fatal.

On top of that, the proxy now includes token usage reporting and an analysis script so you can inspect real usage patterns from logs instead of guessing whether the cache is helping.

### Token counting and usage analysis

Token counting is now explicit instead of being buried inside the proxy flow. When Azure returns final usage data, the response adapter emits a terminal `USAGE:` log line with input tokens, cached input tokens, output tokens, reasoning tokens, total tokens, and a cache-hit percentage derived from the cached-input ratio.

That same usage payload is also what Cursor needs to show context-window usage correctly in the UI and to report the right token totals in dashboards. In other words, this change is not just about local log analysis; it fixes the user-visible accounting Cursor gets back from the proxy.

Those log lines are then parsed by `app/common/token_usage_report.py` and summarized by `scripts/analyze_token_usage.py`. The analyzer can scan a Docker Compose log window, aggregate request counts and token totals, compute overall cache hit rate, estimate spend from configurable per-million-token rates, and surface the largest requests by input size. In other words, this is the branch's concrete token-counting story, not just a vague "usage reporting" note.

### Test coverage and replay fixtures

The branch gained a meaningful replay-test harness and a lot of recorded fixtures. That gives the project a safety net around the exact pieces most likely to regress: response streaming, Azure error handling, tool call transformation, and configuration behavior.

### Ops, packaging, and docs

The supporting files were cleaned up too: `start.sh` was added, Docker and compose settings were adjusted, environment documentation was refreshed, and the README was expanded to explain the current model contract, prompt caching flow, and analysis tooling.

## Commit Trail Since The Fork Point

These are the 12 unique commits on top of `45c5874712f9a05154f4697bfaf056e8535718e1`:

```text
3d8b520 feat: full Cursor proxy with reasoning effort control panel
8f31a6b fix: handle custom_tool_call and all 53 Responses API SSE event types
b6d5f9e fix: use Cursor native reasoning effort
6f27292 fix: make upstream request recording non-fatal
8fb9c5d fix: restore Cursor token usage reporting
7fe0573 feat: enable 24h prompt cache retention and pass cache/reasoning token details to Cursor
134dd33 fix: enable store=true and forward previous_response_id for prompt caching
edfbc60 refactor: clean up REQUEST logging and fix duplicate prev_resp_id assignment
d0977f9 feat: add session_id/x-client-request-id headers and parallel_tool_calls for cache affinity
ccf9752 fix: use cursorConversationId for cache routing instead of per-user hash
600440b refactor: clean up model configuration and repo hygiene
2a9f039 docs: explain prompt cache behavior
```

## Short PR Summary

If you need a concise PR description, this fork now:

- aligns the proxy with real Cursor model ids
- forwards reasoning and verbosity controls natively
- hardens Azure request/response adaptation for tool calls and SSE streams
- makes prompt caching conversation-stable and visible
- adds token usage analysis and a strong replay/regression suite
- cleans up the docs and runtime setup around the new behavior

