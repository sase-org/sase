---
create_time: 2026-05-13 10:56:44
status: done
prompt: sdd/prompts/202605/agent_tier_merge_watermark.md
---
# Plan: Fix transient agent row disappearance across repeated Tier 1 refreshes

## Problem

`sase ace` can briefly drop agent rows after killing or launching agents, then show them again a few seconds later. The
snapshot shows only the newest running rows while older rows are temporarily absent. This happens most often during
state-changing bursts, which are exactly when the TUI can run multiple fast Tier 1 loads before the slower full-history
Tier 2 reconcile completes.

The previous fix made the first incomplete load after a complete-history load patch over the cached full-history list.
That closed one gap, but it only checks the immediately previous `AgentLoadState`.

## Root Cause Hypothesis

The current merge gate in `AgentLoadingApplyMixin._merge_incomplete_load_after_complete_history` requires:

- previous load state exists
- previous load state has `complete_history=True`
- current load state exists
- current load state has `complete_history=False`

After the first Tier 1 patch, `_apply_loaded_agents_prepared` writes `_agent_load_state = load_state`, so the remembered
state becomes incomplete. If another Tier 1 refresh lands before the pending Tier 2 reconcile, the merge gate fails and
the TUI replaces `_agents` with the capped Tier 1 result. Historical or recently completed rows then disappear until the
Tier 2 source scan runs and restores them.

This matches the user-visible behavior:

- rows disappear only briefly
- rows come back without manual intervention
- it is easiest to trigger around launch/kill events, where refreshes are coalesced but can still queue repeated Tier 1
  passes
- the prior dedup backstop can pass all single-incomplete-load regressions while still missing this repeated Tier 1 case

## Product Invariant

Once the TUI has observed a complete-history agent list in the current process, incomplete Tier 1 loads should be
treated as patches over the best known complete-ish list until a new complete-history load arrives. A capped Tier 1
snapshot is allowed to add or update current rows, but it should not shrink the visible universe back to only indexed
recent/current rows.

Before the first complete-history load, Tier 1 should keep its existing capped first-paint behavior.

## Implementation Approach

1. Add an explicit process-local watermark for whether a complete-history agent list has ever been applied.
   - Initialize something like `_agents_seen_complete_history = False` in state init and the loading state protocol.
   - Set it to `True` whenever a load with `load_state.complete_history` is applied.
   - Keep the existing `_agent_load_state` for telemetry and scheduling; do not overload it as the durable watermark.

2. Change `_merge_incomplete_load_after_complete_history` to use the watermark instead of only the immediately previous
   load state.
   - Return early for `load_state is None` or `load_state.complete_history`.
   - Return early if the complete-history watermark is false.
   - Continue using `_agents_with_children` as the merge cache, because `_finalize_agent_list(save_unfiltered=True)`
     already records the post-merge unfiltered list.

3. Preserve the existing merge and dedup behavior inside the helper.
   - Keep suffix guarding for non-canonical shadows.
   - Keep `dedup_running_vs_workflow`, `dedup_by_pid`, and child reattachment after parent replacement.
   - Keep the hideable/always-visible partition rebuild after merging.

4. Add focused regressions in `tests/test_agent_loader_self_heal.py`.
   - A new test should apply a complete Tier 2 list, then an incomplete Tier 1 list, then a second incomplete Tier 1
     list, and assert that historical/cached rows survive the second incomplete load.
   - The test should confirm the pre-full-history behavior remains capped by keeping
     `test_incomplete_load_before_complete_history_still_replaces_list` green.
   - Include a small launcher/kill-shaped scenario if needed: first incomplete load introduces a new active row, second
     incomplete load contains only that active row, and an older cached row remains visible.

5. Validate in layers.
   - Run the new focused test and the full self-heal file.
   - Run `just install` if needed for the editable workspace.
   - Run `just check` per repo memory. If the known pyvision bead configuration blocks it again, report the exact
     blocker and run `just test` plus focused tests against the final code.

## Risks

- If the watermark is set too early, first-paint Tier 1 could begin preserving stale rows before any full-history
  reconcile. The test coverage should explicitly guard against that.
- If `_agents_with_children` contains a search-filtered list, incomplete patches could preserve too little. The current
  load path forces full history when an agent search query is active, and finalize saves the unfiltered pre-fold list,
  so this should remain acceptable.
- If kill/dismiss removes rows optimistically from `_agents_with_children`, the merge must respect `_dismissed_agents`.
  The existing `is_dismissed` filter already does that and should remain unchanged.

## Non-Goals

- Do not widen `dedup_running_vs_workflow` beyond the existing ace-run/run contract.
- Do not change the renderer or grouping code.
- Do not rework the artifact index/query policy.
- Do not modify project memory files without explicit user approval.
