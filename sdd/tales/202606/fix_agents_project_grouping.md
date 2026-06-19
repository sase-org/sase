---
create_time: 2026-06-19 09:27:29
status: done
prompt: sdd/prompts/202606/fix_agents_project_grouping.md
---
# Fix Agents Tab Project Grouping

## Problem

Cycling the Agents tab from `by status` to the UI's `by project` mode updates the app state and info-panel badge, but
the visible list can keep the old status-bucket tree. In a live `sase ace --tmux` capture, the header showed
`[group: by project (o)]` while the list still rendered `Running` and `Done` as level-0 banners.

## Root Cause

The grouping action updates `_grouping_mode` and calls `_refilter_agents()`. The finalize path then calls
`_refresh_agents_display_after_finalize()`, which may choose the incremental display refresh when the agent identities
did not change.

That incremental path only checks the new grouping mode. It allows the fast path when the new mode is
`GroupingMode.STANDARD`, but it does not verify that the existing `AgentList` widgets were also built with `STANDARD`.
Therefore a `BY_STATUS -> STANDARD` transition can patch/highlight existing rows instead of rebuilding the tree, leaving
stale status banners under a project-mode label.

## Implementation Plan

1. Add a narrow incremental-refresh guard that compares each rendered `AgentList` widget's current `_grouping_mode`
   against the app's active `_grouping_mode`.
2. If any existing widget was built under a different mode, force the normal full list rebuild path and record an
   existing fallback reason if one fits, or add a focused fallback reason only if the current trace type requires it.
3. Keep the fix on the display-refresh boundary rather than the tree builder or grouping action, because the tree
   builder is already mode-correct and the action already updates state correctly.
4. Add a regression test that starts with widgets rendered in `BY_STATUS`, switches app state to `STANDARD`, invokes the
   finalize/display refresh path with unchanged agents, and asserts that the full rebuild path is used instead of the
   incremental path.
5. Run the focused TUI/Agents tests for grouping and display refresh.
6. Verify manually with `PYTHONPATH=src sase ace --tmux` so the installed `sase` shim runs this workspace's code,
   navigate to Agents, enable `by project`, and capture the tmux pane. The expected capture should show
   `[group: by project (o)]` with project-name level-0 banners such as `bob-cli`, `sase`, and `home`, not stale
   `Running` / `Done` status buckets.
