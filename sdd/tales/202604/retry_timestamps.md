---
create_time: 2026-04-10 16:51:54
status: done
prompt: sdd/prompts/202604/retry_timestamps.md
---

# Plan: Add RETRY Timestamps to Agents Tab Metadata Panel

## Goal

Add "RETRY" timestamps to the Timestamps field in the agent metadata panel on the Agents tab. Each retry attempt records
a new RETRY timestamp, so an agent may have multiple RETRY entries displayed chronologically alongside existing
timestamps (WAIT, BEGIN, PLAN, FBACK, QUEST, CODE, END).

## Context

The retry system already exists in `run_agent_exec_retry.py`. When an LLM provider error matches configured retry
patterns, the agent waits and re-runs. The `retry_state.json` tracks retry count/status for the TUI, but no timestamp is
recorded for when each retry actually starts running.

Other timestamps (PLAN, FBACK, QUEST) are written to `agent_meta.json` via `update_meta_field()` and loaded by
`enrich_agent_from_meta()`. Retries are unique because there can be multiple per agent, so the field must be stored as a
list rather than a single ISO string.

## Design

**Storage format** in `agent_meta.json`:

```json
{
  "retry_started_at": ["2026-04-10T12:00:00+00:00", "2026-04-10T12:05:00+00:00"]
}
```

This is a list of ISO timestamps, one per retry attempt (including fallback). This differs from `plan_submitted_at` (a
single string) because multiple retries are the norm, not the exception.

## Changes

### 1. Write RETRY timestamps during retry execution

**File**: `src/sase/axe/run_agent_exec_retry.py`

When the retry wait finishes and the agent transitions to `running_retry` (line ~90) or `running_fallback` (line ~111),
append the current UTC timestamp to the `retry_started_at` list in `agent_meta.json`.

A new helper `append_meta_list_field(artifacts_dir, key, value)` in `run_agent_helpers.py` handles the read-append-write
pattern cleanly, since `update_meta_field` only supports scalar values.

### 2. Add `retry_times` field to Agent model

**File**: `src/sase/ace/tui/models/agent.py`

Add `retry_times: list[datetime] = field(default_factory=list)` alongside the existing `plan_times`, `feedback_times`,
`questions_times` fields.

### 3. Load retry timestamps from agent_meta.json

**File**: `src/sase/ace/tui/models/_loaders/_artifact_loaders.py`

In `enrich_agent_from_meta()`, parse the `retry_started_at` list from `agent_meta.json` and populate
`agent.retry_times`. Follow the same pattern as other timestamp fields but handle a list of ISO strings instead of a
single string.

### 4. Display RETRY in timestamps_display

**File**: `src/sase/ace/tui/models/agent.py`

In the `timestamps_display` property, add `retry_times` entries to the `middle` list with the tag "RETRY". They'll be
sorted chronologically with the other middle timestamps automatically.

## Tag Width

The current `tag_width` is 5 (matching "BEGIN" and "FBACK"). "RETRY" is also 5 characters, so no width adjustment
needed.
