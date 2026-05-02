---
create_time: 2026-04-08 00:28:32
status: done
prompt: sdd/prompts/202604/llm_token_metrics.md
---

# Plan: LLM Token & Cost Metrics (Claude Code)

## Goal

Add token usage tracking for Claude Code agent runs. Parse token data from the existing stream-json output, record it as
Prometheus metrics, persist it in artifacts, and surface it through the `sase telemetry` CLI.

## Context

Claude Code is invoked with `--output-format stream-json`. The JSON event stream includes `result` events with `usage`
dicts containing `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, and `cache_read_input_tokens`.
Currently, `_process_json_line()` in `_subprocess.py` only extracts diagnostic text from `result` events — the usage
data is discarded.

The existing telemetry system has 4 LLM metrics (invocations, duration, errors, retries) — all labeled by `provider` but
none tracking token consumption, which is the primary cost driver.

## Design

### Data Flow

```
Claude Code stdout (stream-json)
  → _process_json_line() extracts usage from result events
  → Accumulated in UsageAccumulator passed through the call chain
  → Written to artifacts/usage.json alongside live_reply.md
  → Prometheus counters incremented in _invoke.py (same place as existing LLM metrics)
  → Visible via `sase telemetry snapshot`, `sase telemetry health`, etc.
```

### Artifacts Approach

Follow the existing pattern used for `live_reply.md` and `live_reply_timestamps.jsonl` — write a `usage.json` file to
`SASE_ARTIFACTS_DIR`. This is simpler than threading usage data through return values and makes the data available for
post-hoc analysis regardless of telemetry being enabled.

## Phases

### Phase 1: Parse Token Usage from Claude Code Events

**Files:** `src/sase/llm_provider/_subprocess.py`

- Add a `usage_totals` dict parameter to `_process_json_line()` that accumulates token counts across events
- When `event_type == "result"`, extract `usage` dict fields: `input_tokens`, `output_tokens`,
  `cache_creation_input_tokens`, `cache_read_input_tokens`
- Add to running totals (a single agent run may have multiple result events due to interrupt/resume cycles)
- Update `stream_and_parse_json_output()` to:
  - Initialize `usage_totals` dict
  - Pass it to `_process_json_line()`
  - Return it as a 4th element: `(text, stderr, return_code, usage_totals)`
  - Write `usage.json` to `SASE_ARTIFACTS_DIR` (if set) at the end

### Phase 2: Thread Usage Through Provider Return Chain

**Files:** `src/sase/llm_provider/_subprocess.py`, `src/sase/llm_provider/claude.py`, `src/sase/llm_provider/base.py`,
`src/sase/llm_provider/_invoke.py`

- `stream_and_parse_json_output()` already returns a tuple — extend it to 4 elements
- `ClaudeCodeProvider._run_subprocess()` returns tuple — extend to include usage
- `ClaudeCodeProvider.invoke()` accumulates usage across interrupt/resume cycles and returns it alongside response text
- Update `LLMProvider.invoke()` base signature to return `InvokeResult` (a small dataclass/NamedTuple with `content` and
  `usage` fields) instead of bare `str`
- Update `invoke_agent()` in `_invoke.py` to unpack the result and record token metrics
- Other providers (Codex, Gemini) return `InvokeResult` with `usage=None` for now

### Phase 3: Add Prometheus Token Metrics

**Files:** `src/sase/telemetry/metrics.py`

Add 3 new counters to the LLM Provider section:

- `LLM_INPUT_TOKENS` → `sase_llm_input_tokens_total` (counter, labels: `[provider]`)
- `LLM_OUTPUT_TOKENS` → `sase_llm_output_tokens_total` (counter, labels: `[provider]`)
- `LLM_CACHE_READ_TOKENS` → `sase_llm_cache_read_tokens_total` (counter, labels: `[provider]`)

Record these in `_invoke.py` right after the existing `LLM_INVOCATIONS` / `LLM_INVOCATION_DURATION` calls, using the
usage data from `InvokeResult`.

Note: `cache_creation_input_tokens` is written to `usage.json` for analysis but doesn't need its own Prometheus counter
— it's a niche metric that's better served by post-hoc analysis of artifact files.

### Phase 4: Update Telemetry CLI

**Files:** `src/sase/telemetry/cli_snapshot.py`, `src/sase/telemetry/cli_health.py`

- The snapshot and dashboard commands will automatically pick up the new metrics since they render from scraped
  Prometheus data and use the catalog
- Add a token usage health check in `cli_health.py`: show total tokens consumed as an informational line (no
  warn/critical thresholds — token consumption is expected, not an error condition)

### Phase 5: Tests

**Files:** `tests/telemetry/`, `tests/llm_provider/`

- Test `_process_json_line()` with mock `result` events containing `usage` dicts
- Test usage accumulation across multiple events
- Test `usage.json` is written to artifacts dir
- Test new Prometheus counters are incremented correctly
- Test `InvokeResult` is returned by providers with/without usage data
