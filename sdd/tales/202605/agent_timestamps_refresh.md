---
create_time: 2026-05-21 09:13:15
status: done
prompt: sdd/prompts/202605/agent_timestamps_refresh.md
---
# Fix Agents Tab Timestamp Loss on Refresh

## Context

The Agents tab detail panel renders `PLAN` and `CODE` from the selected `Agent` model:

- `PLAN` comes from `agent.plan_times`, loaded from `agent_meta.json` / `AgentMetaWire.plan_submitted_at`.
- `CODE` comes from `agent.code_time`, which is not a persisted parent field. It is derived by
  `apply_status_overrides()` from a `.code` follow-up child whose `parent_timestamp` points at the plan-chain parent.

Auto-refresh often uses a Tier 1 artifact-index load. Once a complete-history load has happened, Tier 1 rows are merged
over the cached full list in `merge_incomplete_load_after_complete_history()`.

## Root Cause

The Tier 1 merge can replace a cached parent row with a freshly loaded parent row while preserving cached children as
separate rows. The normal loader computes relationship-derived fields before this merge. After the merge, the fresh
parent and cached child coexist, but the relationship pass is not rerun, so fields derived from children disappear from
the replacement parent:

- `code_time` is lost, so `CODE` disappears from the detail-panel timestamp list.
- `runtime_children` is lost, so active parent runtime suffixes can also regress.
- Other child-derived fields such as propagated feedback/question metadata and follow-up lists are vulnerable to the
  same stale-parent replacement pattern.

This matches the observed "disappears on every auto-refresh" behavior: the detail panel is rendering the current model
accurately; the model has been partially de-enriched by the incomplete-history merge.

## Implementation Plan

1. Add a regression test for the Tier 1 patch merge.
   - Seed cached complete-history state with a plan-chain parent and `.code` child where the parent already has
     `code_time` / `runtime_children`.
   - Apply an incomplete Tier 1 load containing a fresh replacement parent but not the child.
   - Assert the merged parent still shows `CODE`, has the coder as a runtime child, and keeps the child row attached.

2. Normalize relationship-derived state after incomplete-history merge.
   - In `src/sase/ace/tui/actions/agents/_loading_compute_merge.py`, after the merged list is deduped and children are
     reattached, split the flat rows into top-level/follow-up rows and workflow-step rows.
   - Re-run the same relationship and ordering helpers used by the normal loader:
     `apply_status_overrides(top_level_rows, workflow_steps)` and `sort_and_reorder(top_level_rows, workflow_steps)`.
   - Then recompute `always_visible`, `hideable`, and `hidden_count` from the normalized list.

3. Keep the change scoped to the TUI merge boundary.
   - No Rust/core change is needed because the bug is in presentation-state merging after the Python loader has already
     received valid rows.
   - Do not persist `code_time` to metadata as the primary fix; it is intentionally derived from follow-up rows and the
     merge should preserve that invariant.

4. Verify with focused tests first.
   - Run the new merge regression and nearby timestamp/status override tests.
   - Then run `just check` as required for repo code changes.
