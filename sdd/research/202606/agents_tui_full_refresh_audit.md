# Agents TUI Full Refresh Audit

Status: Final consolidated research
Date: 2026-06-08

## Request

Full agent refreshes in the ACE TUI are still slow, especially around agent
launch. Audit where full refreshes are still necessary and plan how to remove
the avoidable ones.

This consolidates and verifies:

- `sdd/research/202606/incremental_agent_refresh.md`
- `sdd/research/202606/agents_tui_remaining_full_refresh_matrix.md`

## Short Answer

"Full refresh" currently means three different costs:

1. Tier 2 full-history source scan.
2. Tier 1 broad visible-inbox reload through `_load_agents_async`.
3. Full display rebuild through `_refresh_agents_display(list_changed=True)`.

Tier 2 scans are now mostly intentional: startup repair, explicit manual full
history, revive/archive recovery, and index fallback. The remaining hot-path
problem is that many precise events still flow through a broad Tier 1 reload
and then a full display rebuild.

The highest-value fix is launch. The spawn layer already returns
`AgentLaunchResult`, but the TUI launch bridge drops it and schedules a broad
Agents refresh. The display layer can patch and remove rows, but cannot insert
or move rows incrementally, and the current Textual `OptionList` API exposes
append/remove/replace/reset, not indexed insertion. That makes "new row
appeared" the key missing operation.

Recommended direction:

- propagate launch results back to the TUI;
- add targeted artifact-dir deltas so known marker changes do not reload the
  whole visible inbox;
- add a display diff layer with row patch/remove, affected-panel rebuild, and
  eventually true row insert/move;
- keep broad Tier 1/Tier 2 refreshes as explicit fallback and repair paths.

## Verified Current State

### Async Refresh Pipeline

`request_agents_refresh(...)` coalesces bursty sources such as launch fan-out
and calls `_schedule_agents_async_refresh(...)`
(`src/sase/ace/tui/actions/agents/_loading_refresh.py`). The scheduler is
last-request-wins, defers while the j/k navigation gate is active, and preserves
explicit `full_history=True` requests.

After `_load_agents_async(...)` finishes disk/index work, apply/finalize still
ends with `_refresh_agents_display(list_changed=True, defer_detail=True)` when
the Agents tab is active (`_loading_finalize.py`). That means even a future
narrow loader needs a display-diff step, or it will still repaint all Agents
panels.

### Loader Capabilities And Gaps

Normal TUI loads use the artifact index when present:
`AgentArtifactIndexQueryWire(include_active=True, include_recent_completed=True,
include_full_history=False, recent_completed_limit=200)`.

The code already has useful targeted index write helpers:

- `upsert_agent_artifact_index_row(...)`
- `upsert_agent_artifact_index_artifacts(...)`
- `update_agent_artifact_index_for_marker_mutation(...)`

The missing read-side capability is an exact artifact-dir/raw-suffix batch
query. `AgentArtifactScanOptionsWire` can restrict by workflow directory or
project, but not by an exact set of artifact dirs. `AgentArtifactIndexQueryWire`
can query active/recent/full-history sets, but not "these artifacts changed".

### Display Capabilities And Gaps

The display layer already has these fast paths:

- j/k highlight updates via `update_highlight`;
- row mutation via `_try_patch_agent_row(...)` and `AgentList.patch_agent_row`;
- row removal via `_try_remove_agent_rows(...)` and `AgentList.try_remove_rows`;
- runtime suffix ticks via `patch_active_runtime_rows`.

Those paths are conservative and fall back to full display rebuild for active
search, unsupported grouping, missing row context, width growth, multi-panel
changes, or workflow tree ambiguity.

There is no display primitive for insertion or move. `build_list(...)` still
does `clear_options()` and re-adds every row. The installed Textual
`OptionList` supports `add_option(s)`, `remove_option_at_index`, and
`replace_option_prompt_at_index`, but has no supported indexed insert API. A
true insert therefore needs either a careful local `AgentList` splice helper
over Textual internals or a safer affected-panel rebuild fallback first.

## Audit Matrix

| Area | Current behavior | Keep full refresh? | Plan |
| --- | --- | --- | --- |
| Startup first load | Startup schedules the first async Agents load after mount. | Yes. | Keep Tier 1 broad load; there is no prior list to diff. |
| Manual refresh | `action_refresh()` schedules source `manual`, `full_history=False`. | Yes. | Keep as explicit user reconcile. |
| Manual full history | `action_refresh_agents_full_history()` sets `full_history=True`. | Yes. | Keep as explicit heavy repair/history command. |
| Idle Tier 2 reconcile | `_maybe_trigger_idle_tier2_reconcile()` runs full history only when repair/fallback state is armed. | Yes. | Keep, but tag telemetry clearly as repair/fallback. |
| Single launch | `_launch_background_agent()` calls `spawn_agent_subprocess(...)` but returns `None`; caller schedules `_schedule_agents_async_refresh`. | No. | Return `AgentLaunchResult`, apply launch delta, then narrow reconcile. |
| Workflow launch | Successful workflow dispatch schedules `_schedule_agents_async_refresh`. | Often no. | Use workflow/step launch records where available; keep fallback for complex parent/child reshapes. |
| Multi-prompt/model launch | Calls `request_agents_refresh("launch")` before launch and after spawned slots; results are only counted. | No. | Remove pre-refresh; apply one result delta per spawned slot and batch display work. |
| Repeat/bulk launch | Schedules `request_agents_refresh("launch")` per slot; repeat callbacks currently get records whose results are `None`. | No. | Make spawn callbacks return results; batch deltas per UI tick. |
| Watcher marker changes | `_on_artifact_change()` maps paths to dirty flags; auto-refresh broad-loads when `_dirty_agents`. | Sometimes. | Preserve bounded changed artifact dirs; route known small batches through targeted deltas. |
| STARTING poll | Marker stat changes call `request_agents_refresh("starting_poll")`. | Usually no. | Target-reconcile the agent's artifact dir and patch status. |
| Notifications | Completion/status projection can patch rows, but several flows still request notification Agents refresh. | Sometimes. | Patch visible rows first; broad reload only when notification references an absent/hidden artifact. |
| Filter/search | Actions call `_refilter_agents()` and then schedule source `filter`. | Disk reload no; display rebuild often yes. | After first load, refilter cached agents and refresh content index only. |
| Dismiss/kill | Already mutate memory and try row removal before rebuilding. | Only fallback. | Expand remove coverage and add affected-panel rebuild before all-panel rebuild. |
| Revive | Refills cache then schedules full-history refresh. | Partly. | Use targeted insertion when restored artifact dirs are known; keep full history for archive discovery/repair. |
| Rename | Writes `agent_meta.json`, upserts index, mutates memory, then full display rebuilds. | Disk no; display sometimes. | Patch same-panel row; rebuild affected panel if sort/group/width changes. |
| Tagging | Mutates tags, invalidates panel cache, then full display rebuilds. | Disk no; display sometimes. | Patch same-panel tags; rebuild source/target panels when tag panels change membership. |
| Mark/unread/approve | Existing patch paths with full rebuild fallback. | Only fallback. | Keep; later downgrade fallback to affected-panel rebuild. |
| Clear marks / mark all read | Full display rebuild. | No. | Batch patch affected rows and info/count panels. |
| Entry jump hints | Enter/exit jump mode rebuilds list to show hint text. | No, but lower priority. | Replace with overlay or visible-row patch. |
| Panel grouping/fold/search reshuffle | Rebuilds panel/list structure. | Yes for display. | Keep display rebuild; no disk reload needed after cache exists. |
| Unknown watcher burst/error recovery | Broad reload or full history may run. | Yes. | Keep as safety net with explicit fallback reason. |

## Critical Corrections From Verification

- Launch files live under `src/sase/ace/tui/actions/agent_workflow/`, not
  `actions/agents/`.
- `spawn_agent_subprocess(...)` returns `AgentLaunchResult`, but
  `_launch_background_agent(...)` discards it. TUI spawn callbacks in single
  and repeat launch return `None`, so `LaunchExecutionRecord.result` cannot be
  useful there until this is fixed.
- Multi-prompt and multi-model paths already receive result lists from
  `launch_multi_prompt_agents(...)`, but use them only for counts/notifications.
- The local Textual `OptionList` does not expose `insert_option_at_index`; the
  insert plan must account for that API gap.
- The scan/index wire APIs have exact project/workflow filters, but not exact
  artifact-dir/raw-suffix delta reads.

## Implementation Plan

### Phase 1: Telemetry And Fallback Taxonomy

Add structured trace fields for:

- source: `launch`, `auto_refresh`, `starting_poll`, `notification`, `filter`,
  `tab_switch`, `manual`, `manual_full_history`, `repair`;
- cost: `tier2_full_history`, `tier1_broad_load`, `artifact_delta_load`,
  `display_full_rebuild`, `display_panel_rebuild`, `row_patch`, `row_insert`,
  `row_remove`;
- fallback reason: `missing_result`, `no_artifact_dir`, `query_api_missing`,
  `active_search`, `grouping_unsupported`, `width_growth`,
  `panel_membership_change`, `workflow_tree_change`, `dirty_overflow`,
  `unknown_path`, `persistence_error`.

This makes it possible to prove that launch no longer admits broad reloads in
the common path.

### Phase 2: Propagate Launch Results

Change `_launch_background_agent(...)` to return `AgentLaunchResult`, and make
all TUI spawn callbacks return that result to `execute_launch_plan(...)`.

Then route all launch surfaces through a common launch-delta callback:

- single prompt;
- workflow dispatch where records are available;
- multi-prompt;
- multi-model;
- repeat;
- bulk.

Remove immediate pre-launch `request_agents_refresh("launch")` calls once the
UI has launch-progress feedback and result deltas.

### Phase 3: Add Targeted Artifact Delta Loading

Create a TUI-facing delta service that accepts exact artifact dirs or raw
suffixes and returns normalized `Agent` values through the same domain pipeline
as broad loads: dead-PID filtering, deduplication, workflow overrides,
dismiss/hide projection, and ordering.

Close the core API gap in `../sase-core` or the Python facade:

- either scan a bounded list of artifact directories directly;
- or add exact artifact-dir/raw-suffix filters to the index query wire.

Keep broad Tier 1 load as fallback when the delta cannot be read or normalized.

### Phase 4: Add Display Diff Operations

Compute `(added, removed, changed, moved, structural)` by agent identity before
calling full display rebuild. Apply in this order:

1. Patch changed visible rows with `_try_patch_agent_row(...)`.
2. Remove disappeared rows with `_try_remove_agent_rows(...)`.
3. Insert or move rows when the display layer supports it.
4. Rebuild only affected panel(s).
5. Rebuild all Agents panels.
6. Reload from disk.

Because Textual lacks indexed insert, the first practical version can skip
true row insertion and rebuild only the affected panel. That still avoids the
worst all-panel rebuild and keeps the final true-insert work isolated.

### Phase 5: Convert Launch Hot Paths

Use `AgentLaunchResult` as the seed:

- `output_path` gives the artifact dir;
- `pid`, `workspace_num`, `workspace_dir`, `project_file`, `project_name`,
  `workflow_name`, `cl_name`, `timestamp`, and `agent_name` support an
  optimistic STARTING row;
- exact artifact-dir reconcile replaces or confirms the optimistic row.

Critical correctness rule: the optimistic identity must match the loader's
identity, or reconcile will duplicate rows. Identity/order construction belongs
in shared core or must call the same existing loader helpers, not a new
hand-written tuple in the TUI.

Fallback to current broad refresh when the result is missing, artifact scanning
fails, the active search/grouping mode cannot display the delta safely, or the
workflow parent/child tree changes structurally.

### Phase 6: Convert Watcher, STARTING Poll, And Notifications

Store a bounded dirty artifact-dir queue alongside `_dirty_agents`.

For known marker files (`agent_meta.json`, `running.json`, `waiting.json`,
`done.json`, `pending_question.json`, `workflow_state.json`, `plan_path.json`,
`retry_state.json`), upsert the artifact index row, load that exact artifact,
and patch/insert/remove/move the affected display rows.

Keep broad auto-refresh for unknown paths, path batches above the queue limit,
root-level project changes, directory moves, index repair signals, and
persistence errors.

Notification flows should prefer existing snapshot projection and row patching.
Request a broad Agents refresh only when the referenced artifact is absent from
memory or cannot be resolved to a visible identity.

### Phase 7: Remove Redundant Display-Only Reloads

After first load:

- filter/search actions should only `_refilter_agents()` and refresh the
  content-search index;
- rename/tag should patch rows or rebuild affected panels;
- clear marks and mark-all-read should batch patch visible rows;
- entry jump hints should use overlay/visible-row patching if this path remains
  noticeable.

### Phase 8: Split Revive

Use targeted upsert/scan/insert for revive when the revived artifact dirs are
known from the bundle/archive operation. Keep `schedule_revive_full_history_refresh`
for archive discovery, missing artifact dirs, index repair, or explicit history
recovery.

## Verification Plan

Add tests and perf probes before removing broad-refresh calls:

- launching a single agent on the Agents tab applies a launch delta and does not
  call `_load_agents_async(source="launch")` in the successful path;
- multi-prompt/model/repeat/bulk launch batches apply result deltas without one
  broad refresh per slot;
- STARTING->RUNNING/DONE marker changes patch or targeted-reconcile one
  artifact dir;
- notification completion/unread changes patch visible rows without broad load
  when identity/artifact dir is known;
- filter/search after first load does not schedule `_schedule_agents_async_refresh`;
- rename/tag same-panel changes patch rows, and panel-moving changes rebuild
  only affected panels;
- dismiss/kill/revive exercise fast path plus documented fallback;
- extend `tests/ace/tui/bench_tui_jk.py` or add a sibling slow benchmark for
  launch-adjacent Agents-tab actions, as called out in
  `memory/long/tui_jk_baseline.md`.

## Bottom Line

Keep full refreshes for first load, explicit repair, full-history recovery, and
structural display changes. Remove them from known local mutations. Agent
launch is the first target: propagate the spawn result, apply a launch delta,
reconcile the exact artifact dir, and only fall back to broad reload when a
specific safety gate fails.
