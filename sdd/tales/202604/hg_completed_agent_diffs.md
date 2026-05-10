---
create_time: 2026-04-08 18:46:49
status: done
prompt: sdd/prompts/202604/hg_completed_agent_diffs.md
---

# Fix: Completed Agent Diffs Not Showing on Mercurial (retired Mercurial plugin)

## Problem

Completed agent diffs don't display in the TUI on the work machine (retired Mercurial plugin / Mercurial VCS). Live diffs for running
agents work fine on both git and hg machines.

## Root Cause

The `hg.yml` xprompt workflow in retired Mercurial plugin is missing a `diff` step. Both `git.yml` and `gh.yml` have a `diff` step
with `finally: true` that captures the agent's changes and outputs a `diff_path`, which gets stored in `done.json` via
`extract_step_output_and_diff_path()`. Without this step, `diff_path` is never written to `done.json`, so the TUI's
`get_agent_diff()` returns `None` for completed hg agents.

### How diffs flow to the TUI for completed agents

1. Workflow `diff` step runs with `finally: true` -> outputs `diff_path`
2. Step output stored in `workflow_state.json`
3. `extract_step_output_and_diff_path()` reads `workflow_state.json` -> finds `diff_path`
4. `diff_path` written to `done.json`
5. TUI `get_agent_diff()` reads the file at `agent.diff_path`

Step 1 is completely missing for `hg.yml`.

### Secondary issue

`CommitWorkflow._write_result_marker()` already writes `diff_path` to `commit_result.json`, but
`extract_step_output_and_diff_path()` doesn't read it from there. Adding `diff_path` extraction from
`commit_result.json` would provide a safety net for all VCS providers.

## Plan

### Phase 1: Add `diff` step to `hg.yml` (retired Mercurial plugin plugin)

**File**: `../retired Mercurial plugin/src/retired_mercurial_plugin/xprompts/hg.yml`

1. Track initial revision in the `prepare` step by adding `hg id -r . --template '{node}'` to record `head_before` in
   its output.

2. Add a `diff` step with `finally: true` after `release`, modeled on `gh.yml`'s diff step (lines 128-155) but using
   Mercurial commands:
   - Compare current rev (`hg id -r . --template '{node}'`) to `prepare.head_before`
   - If commits were made: `hg diff -c .` to capture the last commit's diff
   - If no commits: `hg diff` to capture uncommitted changes
   - Write diff to a temp file, output `diff_path: path` and `meta_commit_message: line`

### Phase 2: Add `diff_path` extraction from `commit_result.json` (sase_101 repo)

**File**: `src/sase/axe/run_agent_helpers.py`

In `extract_step_output_and_diff_path()`, after the existing `commit_result.json` fallback block (lines 100-124), also
extract `diff_path` from `commit_result.json` when no workflow step already provided one. This provides a safety net for
all VCS providers regardless of whether their xprompt workflow has a dedicated diff step.
