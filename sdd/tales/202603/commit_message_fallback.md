---
create_time: 2026-03-30 13:43:52
status: done
---

# Plan: Fix missing "Commit Message:" in TUI when #commit xprompt is not embedded

## Problem

When an agent runs without `#commit` in its xprompt (e.g., `#hg:pat_line_chart_component ... #plan`), the commit stop
hook still fires and the agent creates a commit via the `/sase_hg_commit` skill. The
`CommitWorkflow._write_result_marker()` writes `commit_result.json` to `SASE_ARTIFACTS_DIR` as expected. However, the
`meta_commit_message` field never appears in the TUI's "AGENT DETAILS" panel.

## Root Cause

The `meta_commit_message` metadata flows through two separate paths, and only one works:

1. **Working path (with `#commit`):** The `commit.yml` xprompt's hidden `report` post-step reads `commit_result.json`
   and emits `meta_commit_message` → stored in `workflow_state.json` → `extract_step_output_and_diff_path()` picks it up
   → TUI displays it.

2. **Broken path (without `#commit`):** The agent commits via the stop hook. `commit_result.json` is written to
   `SASE_ARTIFACTS_DIR`. But no xprompt post-step runs to read it. `extract_step_output_and_diff_path()` only reads
   `workflow_state.json`, which has no `meta_commit_message`. The TUI shows nothing.

Evidence from the logpack:

- The xprompt was `#hg:pat_line_chart_component ... #plan` — no `#commit` embedded
- `commit_stop_hook.jsonl` shows `"commit_method": ""` (because `commit.yml`'s `environment: SASE_COMMIT_METHOD` was
  never applied)
- The agent committed successfully (chat log confirms `sase commit` ran)
- The notification has no `commit_message` field in `action_data`

## Fix

Add a fallback in `extract_step_output_and_diff_path()` (`src/sase/axe/run_agent_helpers.py`) to read
`commit_result.json` directly from the artifacts directory when the workflow's step output doesn't already contain
commit metadata.

After extracting `step_output` from `workflow_state.json`, check:

1. Does `step_output` already have `meta_commit_message`? If yes, done.
2. Does `commit_result.json` exist in `artifacts_dir`? If yes, read it and merge `meta_commit_message`,
   `meta_new_commit`, and `meta_changespec` into `step_output` (creating it if None).

This mirrors exactly what the `report` step in `commit.yml` does, but as a built-in fallback in the runner. It ensures
commit metadata is always captured regardless of whether `#commit` was in the xprompt.
