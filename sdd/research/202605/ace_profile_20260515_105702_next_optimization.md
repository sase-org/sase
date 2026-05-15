# `sase ace` Profile 2026-05-15 10:57 - Next Optimization Decision

## Source

- Profile artifact: `.sase/home/tmp/sase/ace_profile_20260515_105702.txt`
- Recorded: 2026-05-15 10:52:46
- Duration: 255.502s wall, 125.687s CPU, 24,769 samples
- Root: `src/sase/main/ace_handler.py:74`
- Context: interactive `sase ace --profile` session after several earlier responsiveness fixes had landed.

## Summary

The most impactful next optimization is **shrinking the UI-thread agent refresh apply/finalize phase**. The profile
shows a 1.192s `_apply_loaded_agents_prepared()` continuation on the Textual event loop after async disk loading
completed. That is exactly the kind of hitch that can block user navigation even though the expensive disk scan itself is
already off-thread.

The external editor dominates one branch of the profile at 56.015s in `subprocess.run()` / `waitpid`, but that is a
deliberate suspended-editor interaction, not ordinary navigation. It should be tracked separately if the UX goal becomes
"keep the TUI interactive while an editor is open"; it is not the next best fix for j/k responsiveness.

Previously-hot paths from `sdd/research/202605/ace_profile_20260515_responsiveness.md` look much less important in this
capture:

- Prompt-panel markdown/Pygments rendering is no longer a sampled multi-second hot path.
- ChangeSpec query corpus compile is not visible as a major continuation.
- Artifact-discovery completion is down to roughly 0.009s, updating footer bindings only.
- Selected-agent detail updates sampled in the low-millisecond to tens-of-milliseconds range.

## New Hot Path

Relevant profile excerpt:

```text
1.378 AceApp._run_agents_async_refresh
└─ 1.321 AceApp._load_agents_async
   └─ 1.192 AceApp._apply_loaded_agents_prepared
      ├─ 0.597 AceApp._merge_incomplete_load_after_complete_history
      └─ 0.507 AceApp._finalize_agent_list
         ├─ 0.237 filter_agents_by_fold_state
         ├─ 0.162 [self] _loading_finalize.py
         └─ 0.102 AceApp._refresh_agents_display
            └─ 0.069 AgentList.update_list / build_list
```

This is after `asyncio.to_thread()` returns. The event loop is blocked while the continuation:

- merges a Tier 1/incomplete snapshot with the cached complete-history list;
- deduplicates RUNNING vs WORKFLOW rows and same-PID rows;
- recomputes always-visible/hideable partitions;
- filters workflow children through fold state;
- restores selection and clears group-fold entries;
- rebuilds the visible `OptionList`.

The biggest individual functions are pure data loops over the agent list:

- `src/sase/ace/tui/actions/agents/_loading_apply.py:_merge_incomplete_load_after_complete_history`
- `src/sase/ace/tui/models/_fold_filter.py:filter_agents_by_fold_state`
- `src/sase/ace/tui/actions/agents/_loading_finalize.py:finalize_agent_list`
- `src/sase/ace/tui/widgets/_agent_list_build.py:build_list`

## Interpretation

This is now more important than startup-only or detail-only work because it can happen during a live session whenever an
agent refresh completes. The loader already avoids blocking while it reads disk, but it hands a large amount of
CPU-bound reconciliation back to Textual in one callback. If a user is pressing `j`/`k` when that callback runs, the
keypresses wait behind the merge/finalize/rebuild step.

The profile also hints that the cost scales with loaded history size, not with the currently visible terminal viewport:

- `_merge_incomplete_load_after_complete_history()` scans cached full-history agents and incoming Tier 1 agents, then
  re-deduplicates the merged list.
- `filter_agents_by_fold_state()` runs three passes and repeatedly calls `Agent.is_workflow_child`, which is a computed
  property rather than a stored field.
- `build_list()` still rebuilds all visible options, not just changed rows, though the observed cost there is smaller
  than the merge/finalize cost.

## Ranked Next Options

### 1. Move post-load reconcile/finalize preparation off the UI thread

Best next target.

Proposed shape:

- Snapshot the UI-owned inputs needed for reconciliation immediately before the await boundary:
  - cached `_agents_with_children`;
  - dismissed identities;
  - fold state data;
  - hide flags;
  - current grouping mode and group-fold registry state;
  - selected identity / prior index.
- Add a worker-safe prepared result for the expensive pure-data parts:
  - incomplete-load merge;
  - fold filtering and fold counts;
  - status override application plan;
  - group keys to keep;
  - selected index restoration result;
  - list of visible agents and row metadata inputs.
- On the UI thread, apply only the minimal mutations and repaint.

This should be split carefully. A good first slice is moving `_merge_incomplete_load_after_complete_history()` into the
existing async prep phase because it accounts for 0.597s and mostly needs cached agents plus dismissed state. It should
return a new `PreparedApplyData` rather than mutating one in place on the UI thread.

Acceptance target:

- No single async agent refresh continuation should block the event loop for more than about 50ms on the profiled tree.
- A trace should show user `j`/`k` input dispatching while disk load and reconcile prep are in flight.

### 2. Optimize fold filtering and identity access

Good second slice, possibly inside the same epic.

`filter_agents_by_fold_state()` consumed 0.237s, with 0.072s under `Agent.is_workflow_child` and 0.114s self time. The
code is straightforward and could be made cheaper by:

- caching `is_workflow_child` and identity-like tuples in local variables during loops;
- reducing three passes to two where possible;
- carrying parent/child relationships from the loader or merge step so fold filtering does not reconstruct them each
  refresh.

This is lower leverage than moving the whole stage off-thread, but useful because folded child filtering is on the
critical path for every finalization.

### 3. Patch `AgentList` rows instead of rebuilding all options

Useful but not the first move.

`AgentList.update_list()` / `build_list()` is only 0.069s in this capture. It is still a correctness-sensitive path and
will matter as the data side gets faster, but optimizing it first cannot remove the 0.597s merge or 0.237s fold-filter
stall. Revisit after worker-prepared finalization gets the UI-thread apply step below 100ms.

### 4. Make external editor launch non-blocking

Not recommended as the immediate responsiveness optimization.

The profile has 56.015s inside `run_editor()` waiting for the external editor process. That is real wall time on the
main thread, but the app is intentionally suspended for terminal editor use. It should become a separate UX decision:
either keep suspend semantics, or launch a detached graphical/editor flow and let ACE remain interactive. It does not
explain refresh-time navigation hitches.

## Recommended Next Bead

Create a focused optimization bead for **agent refresh apply continuation latency**.

Suggested implementation sequence:

1. Add timing/trace spans around `_merge_incomplete_load_after_complete_history`, `filter_agents_by_fold_state`,
   selection restoration, group-key enumeration, and `AgentList.update_list` so before/after captures can attribute the
   remaining continuation cost.
2. Extract `_merge_incomplete_load_after_complete_history()` into a pure worker helper that accepts snapshots of cached
   agents, incoming filtered agents, dismissed identities, `hide_non_run_agents`, and load-state facts.
3. Call that helper from `_load_agents_async()` before returning to UI-thread apply. Keep the sync path behavior
   unchanged or route it through the same helper synchronously.
4. Add tests covering:
   - incomplete Tier 1 load after complete history preserves cached historical rows;
   - newly discovered Tier 1 roots and children keep expected order;
   - dismissed suffix behavior matches the existing implementation;
   - RUNNING vs WORKFLOW and PID dedup still reattach children correctly.
5. Reprofile with `SASE_TUI_TRACE=1 SASE_TUI_PERF=1 sase ace --profile ...` and compare the async refresh continuation
   against this profile's 1.192s baseline.

## Risks

- Selection and fold behavior are easy to regress because finalization mixes data shape, visibility, and current cursor
  state. Snapshot/prepare/apply boundaries need explicit tests.
- Moving more work off-thread means stale results are possible. The existing last-request-wins refresh coalescing should
  be preserved, and worker results should be discarded or re-run if the relevant UI state changes before apply.
- Some finalization inputs are mutable app-owned state. Copy them before sending to a worker; do not let a worker read
  live Textual app attributes.

## Decision

Do **not** spend the next optimization cycle on syntax rendering, ChangeSpec query corpus, artifact footer updates, or
row rendering first. Based on this profile, the next high-impact work is to make async agent refresh completion mostly
off-thread, starting with `_merge_incomplete_load_after_complete_history()` and then `filter_agents_by_fold_state()`.
