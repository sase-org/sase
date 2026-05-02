---
status: pending
bead_id: sase-8h82
prompt: sdd/prompts/202603/llm_retry_support.md
---

# Add Configurable LLM Provider Retry & Fallback Support

## Overview

Add user-configurable retry and fallback support for LLM providers. When an agent fails and the error matches
user-configured patterns, the runner will retry up to N times (with configurable wait times between retries), then
optionally try a fallback model once. The TUI Agents tab will display retry state with a countdown timer and
retry/fallback indicators.

## YAML Configuration Design

```yaml
llm_provider:
  provider: ""
  retry:
    # Per-provider retry configuration. Key = provider name (e.g., gemini, claude, codex)
    gemini:
      max_retries: 3
      error_patterns: # Substrings matched (case-insensitive) against error output
        - "rate limit"
        - "503"
        - "overloaded"
        - "quota exceeded"
      wait_times: [30, 60, 120] # Seconds to wait before each retry attempt (1-indexed)
      fallback_model: "gemini-3-flash-preview" # Model to try once after all retries exhausted
    claude:
      max_retries: 2
      error_patterns:
        - "overloaded"
      wait_times: [15, 30]
      fallback_model: "claude-sonnet-4-5-20250514"
```

**Semantics:**

- `max_retries`: Number of retry attempts (0 = no retries). Default: 0 for all providers.
- `error_patterns`: List of substrings. If ANY pattern matches the error output (case-insensitive), the error is
  considered retryable.
- `wait_times`: List of wait durations (seconds) before each retry. If fewer entries than `max_retries`, the last value
  is reused. If empty or missing, defaults to `[30]`.
- `fallback_model`: Model spec to try once after all retries are exhausted. Empty string or missing = no fallback.

## Artifacts: `retry_state.json`

Written to the agent's artifacts directory so the TUI can track retry state:

```json
{
  "status": "retrying",
  "retry_count": 2,
  "max_retries": 3,
  "next_retry_at_epoch": 1710600660.0,
  "wait_seconds": 60,
  "fallback_model": "gemini-3-flash-preview",
  "using_fallback": false,
  "last_error_snippet": "rate limit exceeded..."
}
```

- `status`: `"retrying"` (waiting for next attempt) | `"running_retry"` (retry in progress) | `"running_fallback"`
  (fallback attempt in progress)
- Deleted when the agent completes (success or final failure).

## TUI Design

### Agent List Status Display

**RETRYING status** (new, between RUNNING and DONE):

- Color: Orange (#FF8700) bold — distinct from RUNNING (gold) and FAILED (red)
- Format: `RETRYING (42s)` — countdown to next retry
- The countdown updates on each auto-refresh cycle (every 1s via existing timer)

**After retries, when running the retry or fallback:**

- Status stays `RUNNING` but with an annotation
- Annotation format in agent list entry: `↻N` where N is retry count (e.g., `↻2` = on 2nd retry)
- When using fallback: `↻N▸model` (e.g., `↻3▸flash`) — shows retry count and short fallback model name
- Annotation color: Orange (#FF8700) to match RETRYING

**Agent detail metadata** (right panel header): Shows retry info:

- `Retries: 2/3` and `Fallback: gemini-3-flash-preview` when applicable

### Status Flow

```
RUNNING → (error matches pattern) → RETRYING (42s) → RUNNING ↻1 → (error again) → RETRYING (58s) → RUNNING ↻2
  → (error again) → RETRYING (118s) → RUNNING ↻3 → (error again) → RUNNING ↻3▸flash → DONE/FAILED
```

### Notifications

- **On retry**: Toast notification: `"Agent <name> retrying (attempt 2/3, waiting 60s)"`
- **On fallback**: Toast + persistent notification: `"Agent <name> falling back to <model> after 3 failed retries"`
- **On final failure after fallback**: Standard FAILED notification (already exists)

### done.json Extensions

Add optional retry metadata to the done marker:

```json
{
  "retry_metadata": {
    "total_retries": 3,
    "used_fallback": true,
    "fallback_model": "gemini-3-flash-preview",
    "retry_errors": ["rate limit exceeded", "rate limit exceeded", "503 Service Unavailable"]
  }
}
```

---

## Phase 1: Configuration & Data Models

**Goal**: Add the retry config schema, dataclass, loader, and the retry_state.json schema. No behavioral changes yet.

### Files to Create/Modify

1. **`src/sase/default_config.yml`** — Add empty `retry: {}` under `llm_provider` section
2. **`src/sase/llm_provider/retry_config.py`** (new) — Dataclasses and loader:
   - `ProviderRetryConfig` dataclass: `max_retries`, `error_patterns`, `wait_times`, `fallback_model`
   - `RetryState` dataclass: Fields matching `retry_state.json` schema, plus `write_to(artifacts_dir)` and
     `read_from(artifacts_dir)` class method, and a `delete_from(artifacts_dir)` method
   - `get_retry_config(provider_name: str) -> ProviderRetryConfig | None` — loads from merged config
   - `is_retryable_error(error_output: str, config: ProviderRetryConfig) -> bool` — case-insensitive substring match
   - `get_wait_time(retry_count: int, config: ProviderRetryConfig) -> int` — returns wait seconds for the Nth retry
     (1-indexed), reusing last value if list is shorter
3. **`tests/llm_provider/test_retry_config.py`** (new) — Tests for:
   - Loading config with various YAML structures (empty, partial, full)
   - Error pattern matching (case-insensitive, multiple patterns)
   - Wait time calculation (normal, reuse-last, empty list)
   - RetryState serialization round-trip

### Acceptance Criteria

- `get_retry_config("gemini")` returns `None` with default config (no retry configured)
- `get_retry_config("gemini")` returns populated `ProviderRetryConfig` when config is set
- `is_retryable_error()` correctly matches case-insensitive substrings
- `get_wait_time()` handles edge cases (empty list, shorter list than retries)
- All tests pass

---

## Phase 2: Retry Logic in Agent Runner

**Goal**: Implement the retry/fallback loop in the agent runner. Write `retry_state.json` for TUI consumption.

### Files to Modify

1. **`src/sase/axe_run_agent_runner.py`** — Main changes in `main()`:
   - After `execute_workflow()` returns or raises, check if the outcome is a retryable error
   - To detect errors: check if the workflow raised an exception, OR if `done.json` outcome would be "failed"
   - Import and use `get_retry_config()`, `is_retryable_error()`, `get_wait_time()`, `RetryState`
   - Wrap the workflow execution in a retry loop:
     ```
     for attempt in range(max_retries + 1):  # +1 for initial attempt
         reset workspace if needed
         execute workflow
         if success: break
         if not retryable: break
         if attempt < max_retries:
             write retry_state.json (status=retrying, countdown)
             sleep(wait_time)
             write retry_state.json (status=running_retry)
     if failed and fallback_model:
         write retry_state.json (status=running_fallback)
         execute workflow with fallback model
     delete retry_state.json
     ```
   - **IMPORTANT**: Between retries, the workspace must be cleaned/reset to avoid state pollution. Use existing
     `prepare_workspace()` for this.
   - **IMPORTANT**: Check `was_killed()` during the wait loop (poll in 1-second increments instead of one big sleep) so
     the user can still kill a retrying agent from the TUI.
   - Send notifications on retry and fallback (import from `sase.notifications.senders`)

2. **`src/sase/axe_run_agent_phases.py`** — Extend `build_done_marker()`:
   - Add optional `retry_metadata` parameter (dict with `total_retries`, `used_fallback`, `fallback_model`,
     `retry_errors`)
   - Include in the marker dict when present

3. **`src/sase/notifications/senders.py`** — Add two new notification helpers:
   - `notify_agent_retry(sender, cl_name, attempt, max_retries, wait_seconds, error_snippet)` — lightweight notification
     for retry events
   - `notify_agent_fallback(sender, cl_name, fallback_model, total_retries)` — notification for fallback events

4. **`src/sase/llm_provider/retry_config.py`** — May need minor additions:
   - Helper to extract a short error snippet from full error output (truncate to ~100 chars)

5. **`tests/test_axe_run_agent_runner_retry.py`** (new) — Tests for:
   - Retry loop executes correct number of times
   - Non-retryable errors skip retry
   - Fallback model is tried after max retries
   - `was_killed()` during wait aborts retry loop
   - `retry_state.json` is written/deleted correctly
   - `done.json` includes retry_metadata

### Key Implementation Detail: How to Detect Retryable Errors

The agent runner calls `execute_workflow()` which internally calls `invoke_agent()`. Currently:

- On exception: the runner catches it and writes `done.json` with `outcome="failed"`, `error=str(e)`
- On success: writes `done.json` with `outcome="completed"`

For retry, we need to intercept BEFORE the done marker is written. The approach:

1. Wrap the `execute_workflow()` call in a try/except
2. On exception, capture the error string
3. Check `is_retryable_error(error_string, retry_config)`
4. If retryable AND attempts remain, loop back instead of writing done marker

For cases where `invoke_agent()` returns an error AIMessage (not an exception), we need to check the response content
too. This means `execute_workflow()` needs to surface whether the last step's response was an error. Examine how
`execute_workflow()` communicates results back — it may already raise on failure, or we may need to check the workflow
state file.

### Acceptance Criteria

- Agent retries N times on retryable errors with correct wait times
- Agent uses fallback model after exhausting retries
- Agent does NOT retry on non-matching errors
- Agent can be killed during retry wait
- `retry_state.json` accurately reflects state throughout the lifecycle
- `done.json` includes retry metadata on completion
- Notifications fire on retry and fallback events

---

## Phase 3: TUI Agents Tab Integration

**Goal**: Display retry state in the TUI with countdown timer, retry indicators, and proper status rendering.

### Files to Modify

1. **`src/sase/ace/tui/models/agent.py`** — Add retry fields to Agent dataclass:
   - `retry_count: int = 0` — number of retries completed so far
   - `max_retries: int = 0` — configured max retries
   - `retry_next_at_epoch: float | None = None` — epoch time of next retry (for countdown)
   - `retry_wait_seconds: int = 0` — total wait for current retry
   - `using_fallback: bool = False` — whether currently using fallback model
   - `fallback_model: str | None = None` — fallback model name
   - `retry_status: str | None = None` — "retrying" | "running_retry" | "running_fallback" | None
   - Update `to_bundle_dict()` and `from_bundle_dict()` for new fields

2. **`src/sase/ace/tui/actions/agents/_core.py`** — Extend agent loading:
   - When loading RUNNING agents, check for `retry_state.json` in artifacts dir
   - If found, populate the new retry fields on the Agent dataclass
   - Map retry_status to display status:
     - `"retrying"` → status override "RETRYING"
     - `"running_retry"` → keep "RUNNING" (but set retry_count)
     - `"running_fallback"` → keep "RUNNING" (but set using_fallback)

3. **`src/sase/ace/tui/widgets/agent_list.py`** — Render retry indicators:
   - Add "RETRYING" to status color map: `"RETRYING" → "#FF8700"` (orange, bold)
   - When `status == "RETRYING"`: compute countdown from `retry_next_at_epoch`, display `RETRYING (Ns)`
   - When `retry_count > 0` and status is "RUNNING": append `↻N` annotation (orange)
   - When `using_fallback`: append `▸<short_model>` after the retry count annotation
   - Helper: `_short_model_name(model: str) -> str` — extracts a short display name (e.g., `"gemini-3-flash-preview"` →
     `"flash"`, `"claude-sonnet-4-5-20250514"` → `"sonnet"`)

4. **`src/sase/ace/tui/widgets/agent_detail.py`** — Show retry info in header:
   - When agent has `retry_count > 0` or `using_fallback`, add a line to the metadata display: `Retries: 2/3` and
     optionally `Fallback: gemini-3-flash-preview`

5. **`src/sase/ace/tui/styles.tcss`** — Add styling for RETRYING status if needed (the color is applied inline via Rich
   Text, so this may not need CSS changes)

6. **`src/sase/ace/tui/actions/agents/_notifications.py`** — Ensure RETRYING agents are not counted as "done":
   - RETRYING status should be treated as an active status (like RUNNING/WAITING)
   - The existing `_DISMISSIBLE_STATUSES` check in `agent_list.py` already excludes non-DONE/FAILED, so this should work
     naturally

7. **`src/sase/ace/tui/widgets/agent_detail.py`** — Add "RETRYING" to `ACTIVE_STATUSES` set so the detail panel treats
   retrying agents as active (shows live content, not stale)

### Acceptance Criteria

- RETRYING status displays in orange with countdown timer
- Countdown updates on each refresh cycle
- `↻N` annotation appears for agents that have retried
- `▸model` annotation appears when using fallback
- Agent detail panel shows retry metadata
- RETRYING agents are treated as active (not dismissible, not done)
- Killed during retry correctly transitions to FAILED/killed state
