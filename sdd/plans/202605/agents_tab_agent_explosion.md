---
create_time: 2026-05-01 13:52:40
status: wip
prompt: sdd/prompts/202605/agents_tab_agent_explosion.md
---
# Diagnose and Fix Agents Tab Agent Explosion

## Problem

The `sase ace` Agents tab is showing hundreds of historical agents when the live working set should be around 30. The
snapshot shows grouped counts like `(untagged) · 870`, many old `FAILED` rows, and repeated workflow fold counts (`×5`,
`×7`, `×8`). A local loader diagnostic reproduced the multiplier: the loader starts from thousands of historical
artifact records and then appends thousands of workflow prompt-step child rows before filtering.

## Current Findings

- `load_all_agents()` loads all completed artifact directories from `~/.sase/projects/*/artifacts`, not only current
  live agents.
- `_sort_and_reorder()` inserts `workflow_agent_steps` for every workflow parent before the Agents-tab hide/filter layer
  runs.
- `is_always_visible()` currently returns true for all workflow children, so `compute_apply_loaded_agents()` cannot hide
  completed workflow children even when `hide_non_run_agents=True`.
- The dismissed index is not a reliable guard for the current artifact set. In this workspace,
  `~/.sase/dismissed_agents.json` contains many entries but none overlap the current loaded artifact suffixes, so
  filtering by dismissed suffix removes almost nothing.
- The user-visible symptom is therefore a product of two leaks: historical completed top-level workflow/agent entries
  plus their completed child step rows.

## Root-Cause Direction

The root behavior to fix is in the Agents-tab visibility pipeline, not in rendering/grouping:

1. Completed non-running workflow children are classified as always visible.
2. Completed top-level agents that are neither dismissed nor hidden also stay visible under the default "hide non-run
   agents" mode.
3. Because child rows share parent timestamps and are inserted after deduplication, even a moderate number of old
   workflow artifacts can inflate grouped counts substantially.

## Implementation Plan

1. Add focused regression coverage for `compute_apply_loaded_agents()`:
   - With `hide_non_run_agents=True`, completed `DONE`/`FAILED` non-running top-level agents should move to
     `hideable_agents` and be excluded from `filtered_agents` when there are active/attention agents.
   - Completed workflow-step children should be hidden with their completed parent, not treated as always visible.
   - Active workflow children (`RUNNING`, `WAITING`, `WAITING INPUT`) should remain visible so expanded active workflows
     still show useful step state.
   - Dismissable failures can remain available through the hidden-count path / toggle, but should not flood the default
     view.

2. Tighten the visibility classifier:
   - Replace the broad "workflow children are always visible" rule with a status-aware rule.
   - Treat active/attention statuses as always visible.
   - Treat completed/dismissable statuses as hideable unless they are explicitly required for an active parent context.
   - Preserve explicit `hidden=True` behavior for axe-spawned or `%hide` agents.

3. Ensure parent/child consistency:
   - If a completed top-level workflow is hidden by default, its completed children should not remain in the visible
     list.
   - If an active parent remains visible and fold state later expands it, active child rows should still be available.

4. Keep scope narrow:
   - Do not change artifact scanning, historical artifact retention, or grouping rendering unless tests show the
     visibility fix is insufficient.
   - Do not rewrite the dismissed-index format in this change unless a compatibility bug appears while adding tests.

5. Verify:
   - Run the new focused tests.
   - Run related agent loader/dismissal/fold tests.
   - Run `just check` after code changes, per repository memory.
