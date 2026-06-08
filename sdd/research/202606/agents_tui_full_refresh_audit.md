# Agents TUI Full Refresh Necessity Audit

Status: Research and implementation plan
Date: 2026-06-08

## Question

Full agent refreshes in the ACE TUI are still expensive, especially around
agent launches. Audit where a full refresh is still necessary and plan how to
remove broad refreshes where targeted updates can keep the Agents tab correct.

This note builds on the completed May work in
`sdd/epics/202605/agents_tab_full_refresh_elimination.md` and the older
research in `sdd/research/202605/agents_tab_full_refresh_elimination.md`.
Those findings are mostly not current defects anymore: normal manual refresh is
now Tier 1, healthy Tier 1 loads report `complete_visible_inbox=True`, and the
idle Tier 2 path is gated to repair/fallback states.

## Short Answer

"Full refresh" now means three different costs:

1. Tier 2 full-history source scan.
2. Broad visible-inbox reload through `_load_agents_async`.
3. Full list-widget rebuild through `_refresh_agents_display(list_changed=True)`.

The first category is much rarer after the May visible-inbox work and should
remain for explicit full-history, repair, archive, and revive flows.

The main remaining problem is the second and third categories. Launches,
inotify artifact changes, notifications, filters, rename/tag edits, and some
archive/revive paths still drive the same broad load/apply/rebuild machinery
even when the triggering event identifies one or a few affected artifact
directories. Agent launch is the highest-value target because the spawn path
already has `AgentLaunchResult` data, but the TUI drops it and schedules
`request_agents_refresh("launch")`.

Recommended direction:

- Introduce a targeted agent-delta pipeline that can upsert/scan one or more
  artifact directories, merge them into the cached agent list, and patch,
  insert, or remove affected rows.
- Propagate `AgentLaunchResult` back to the TUI launch actions and replace
  launch-triggered broad refreshes with optimistic row insertion plus targeted
  reconcile.
- Preserve broad refresh as a fallback when a delta cannot be projected safely,
  when the index reports repair/fallback state, or when a structural UI mode
  really invalidates the whole rendered list.

## Current Refresh Stack

### Tier 2 Full-History Source Scan

Normal refresh no longer requests full history. `action_refresh()` on the
Agents tab calls `_schedule_agents_async_refresh(source="manual",
full_history=False)`, while `action_refresh_agents_full_history()` is the
explicit full-history action (`src/sase/ace/tui/actions/base.py:396` and
`:417`).

The scheduler preserves full-history requests when refreshes coalesce
(`src/sase/ace/tui/actions/agents/_loading_refresh.py:97`). The actual
full-history span is traced as `agents.full_history_refresh`
(`_loading_refresh.py:251`).

`AgentLoadState.needs_full_history_reconcile` now depends on visible-inbox
incompleteness, repair recommendation, or truncation
(`src/sase/ace/tui/models/agent_loader.py:76`). A healthy artifact-index load
returns `complete_visible_inbox=True` and `complete_history=False`
(`agent_loader.py:128`). `_should_arm_full_history_reconcile()` only arms the
deferred Tier 2 path for repair/fallback states
(`src/sase/ace/tui/actions/agents/_loading_apply.py:44`).

This means routine Tier 2 scans should be considered intentional escape hatches,
not normal refresh behavior.

### Broad Visible-Inbox Reload

Even the Tier 1 path is still a broad reload. `_load_agents_async()`:

- merges external dismissed state;
- loads all cached ChangeSpecs with `find_all_changespecs_cached(include_states="all")`;
- calls the tiered loader;
- runs cleanup;
- records repro data;
- prepares and applies a complete list snapshot
  (`src/sase/ace/tui/actions/agents/_loading_disk.py:221`).

The tiered loader queries the artifact index for all active plus recent
completed visible rows, then runs the same dead-PID filtering, deduplication,
workflow override, sorting, and reordering pipeline
(`src/sase/ace/tui/models/agent_loader.py:423`).

This is much cheaper than a full-history source scan, but it is still too broad
for events that name one launched agent or one changed marker file.

### Full List-Widget Rebuild

Every loader apply on the Agents tab ends with
`_refresh_agents_display(list_changed=True, defer_detail=True)`
(`src/sase/ace/tui/actions/agents/_loading_finalize.py:194` and `:392`).

`_refresh_agents_display(list_changed=True)` prunes marks, syncs panel grouping,
and calls `_refresh_panel_widgets()` (`src/sase/ace/tui/actions/agents/_display.py:136`).
Each `AgentList.update_list()` calls `build_list()`, and `build_list()` clears
all options and rebuilds row state from scratch
(`src/sase/ace/tui/widgets/agent_list.py:133`,
`src/sase/ace/tui/widgets/_agent_list_build.py:159`).

The codebase already has some incremental hooks:

- `AgentList.try_remove_rows()` for conservative removals.
- `AgentList.patch_agent_row()` for one-row prompt replacement.
- `AgentList.patch_active_runtime_rows()` for clock suffix updates.
- TUI helpers `_try_remove_agent_rows()` and `_try_patch_agent_row()`
  (`src/sase/ace/tui/actions/agents/_display_panel_patches.py:30`).

Those hooks are useful but narrow. Removal rejects search, non-standard
grouping, workflow parents with visible children, and multi-panel removals.
Row patch rejects BY_STATUS grouping, missing row context, and width growth.
There is no insertion path.

## Inventory Of Remaining Full Refresh Cases

### Startup

Current path:
`_start_post_mount_background_loads()` schedules `_run_agents_async_refresh`
with source `startup` (`src/sase/ace/tui/actions/startup.py:250`).

Necessity:
The first load is necessary. There is no in-memory list yet. It should remain a
Tier 1 visible-inbox load, not a Tier 2 scan, unless index repair is required.

Plan:
Keep this broad load. Optimize first paint separately only after launch and
watcher deltas are solved, for example by lazy panel realization.

### Manual Refresh

Current path:
`action_refresh()` schedules a Tier 1 manual load. Explicit full history is a
separate action (`src/sase/ace/tui/actions/base.py:396`).

Necessity:
Manual Tier 1 refresh is a user repair/reconcile command and should remain.
Manual full-history refresh is intentionally heavy and should remain explicit.

Plan:
Do not remove these. Use them as fallback/recovery paths for failed deltas.

### Idle Tier 2 Reconcile

Current path:
`_maybe_trigger_idle_tier2_reconcile()` schedules `full_history=True` only when
`_agents_history_reconcile_pending` is armed
(`src/sase/ace/tui/actions/agents/_loading_refresh.py:153`).

Necessity:
Keep for index repair, missing/corrupt index fallback, or truncation. Do not use
it for ordinary healthy Tier 1 loads.

Plan:
Add telemetry that distinguishes "repair/fallback Tier 2" from "user requested
full history" so regressions are obvious.

### Agent Launch

Current paths:

- Workflow dispatch success calls `self.call_later(self._schedule_agents_async_refresh)`
  (`src/sase/ace/tui/actions/agent_workflow/_launch_body.py:393`).
- Single-agent launch calls `_launch_background_agent()` and then schedules a
  refresh (`_launch_body.py:498`).
- Multi-prompt, multi-model, bulk, and repeat launch paths call
  `request_agents_refresh("launch")` before launch and/or after each spawned
  slot (`_launch_multi_prompt.py:44`, `_launch_multi_model.py:64`,
  `_launch_bulk.py:111`, `_launch_repeat.py:151`).

Why this is not fundamentally necessary:

- `spawn_agent_subprocess()` already returns `AgentLaunchResult` with PID,
  workspace, output path, project, CL, timestamp, and agent name
  (`src/sase/agent/launch_spawn.py:97` and `:338`).
- `execute_launch_plan()` already returns `LaunchExecutionRecord` objects and
  invokes `on_slot_executed(record)` after each slot
  (`src/sase/agent/launch_executor.py:48`).
- The TUI bridge `_launch_background_agent()` returns `None` and discards the
  launch result (`src/sase/ace/tui/actions/agent_workflow/_launch_background.py:9`).

Plan:
Make launch insertion targeted:

1. Change `_launch_background_agent()` to return `AgentLaunchResult`.
2. Change TUI spawn callbacks to return that result to `execute_launch_plan()`
   and to multi-prompt launch callbacks.
3. Add a UI-side launch delta method that accepts each `AgentLaunchResult`,
   upserts the artifact index row, scans or constructs the launched agent row,
   merges it into `_agents_with_children`, and inserts or rebuilds only the
   affected panel.
4. Remove pre-launch `request_agents_refresh("launch")`; show pending feedback
   through the prompt/footer/notification instead.
5. Keep one broad refresh fallback if the result has no artifact path, the row
   cannot be scanned, the active grouping/search mode cannot accept an insert,
   or a workflow parent/child relationship changes more than one panel.

Expected win:
The first navigation burst after launch should no longer contend with a full
visible-inbox load and full OptionList rebuild.

### Inotify Artifact Changes And Auto Refresh

Current path:
`_on_artifact_change()` receives `changed_paths`, derives dirty surfaces, and
sets `_dirty_agents=True` for relevant marker files
(`src/sase/ace/tui/actions/_event_refresh.py:119`). Auto-refresh later sees
`_dirty_agents` and calls `_load_agents_async(source="auto_refresh")`
(`_event_refresh.py:257`). If the watcher is active and no agent load is due,
it only refreshes the selected live file panel (`_event_refresh.py:229`).

Relevant marker files are `agent_meta.json`, `done.json`, `running.json`,
`waiting.json`, `pending_question.json`, `workflow_state.json`,
`plan_path.json`, and `retry_state.json` (`_event_refresh.py:31`).

Necessity:
A dirty flag is too coarse. Most marker changes identify exactly one artifact
directory and can be handled as a targeted row update or removal.

Plan:

1. Preserve a coalesced set of changed agent artifact directories, not just a
   boolean dirty flag.
2. On the auto-refresh tick, route small unambiguous batches through an
   `apply_agent_artifact_deltas()` path.
3. For each changed directory, upsert the artifact index with
   `update_agent_artifact_index_for_marker_mutation()` or
   `upsert_agent_artifact_index_artifacts()`
   (`src/sase/core/agent_artifact_index_lifecycle.py:219`).
4. Scan/query only those rows, merge them into the in-memory list, and patch,
   insert, move, or remove affected rendered rows.
5. Fall back to the existing broad load for ambiguous paths, large bursts,
   missing deleted directories, index errors, or structural workflow changes.

### Notifications And Completion Polling

Current path:
Auto-refresh polls completions as a separate notifications surface. If polling
finds a new agent notification and the Agents tab is visible, it calls
`request_notification_agents_refresh(self)` when a normal agents load is not
already due (`src/sase/ace/tui/actions/_event_refresh.py:318` and `:338`).

Necessity:
Most completion notifications correspond to one agent identity or raw suffix.
A broad load should be a fallback, not the default.

Plan:
Extend notification refresh requests to carry affected identities, raw suffixes,
or artifact dirs when available. Patch unread/completed state in memory first,
then targeted-scan the affected artifact directory. Use broad refresh only when
the notification cannot be resolved to a visible row.

### Filter And Search

Current path:
Toggling hide-non-run and editing the Agents search query both call
`_refilter_agents()` and then schedule `_schedule_agents_async_refresh(source="filter")`
(`src/sase/ace/tui/actions/agents/_filter_actions.py:12`). `_refilter_agents()`
already starts from `_agents_with_children` and schedules content-search index
refresh when needed (`src/sase/ace/tui/actions/agents/_loading_filter.py:65`).

Necessity:
The async broad reload is usually redundant. Search no longer has to promote to
full history; normal Agents search should search the visible inbox. Archive or
revive search is a separate history-bearing flow.

Plan:
Remove the filter-triggered broad refresh after first load. Keep a cold-cache
guard: if `_agents_first_load_done` is false or `_agents_with_children` is
empty, schedule the normal Tier 1 load. Otherwise refilter cached agents and
refresh the content index only.

### Dismiss And Kill

Current path:
Dismiss and kill already try fast in-memory removal paths, with fallback to
full display rebuild or broad refresh for persistence errors. The remove helper
is conservative and rejects search, non-standard grouping, multi-panel removals,
and workflow parents with visible children.

Necessity:
The fallback is currently necessary for those unsupported structures, but not
because disk state must be reloaded.

Plan:
Broaden the incremental display layer:

- update banner counts during removal instead of waiting for the next rebuild;
- allow targeted rebuild of affected panels rather than all panels;
- support BY_DATE and BY_STATUS group keys;
- handle workflow parent plus child removals as one tree delta;
- support search-filtered removal by mapping rendered rows back to identities.

### Approve, Mark, Unread, Wait/Resume

Current path:
These actions already use `_try_patch_agent_row()` or list_changed=false paths
for the common case, with broad display rebuild fallback.

Necessity:
Keep the fallback for width growth or unsupported grouping. These are not the
main cause of broad disk reloads.

Plan:
After the panel-delta layer exists, convert remaining fallback cases from full
display rebuild to affected-panel rebuild where possible.

### Rename And Tag Changes

Current path:
Renaming writes `agent_meta.json`, updates the artifact index row, mutates the
in-memory agent, and then calls `_refresh_agents_display(list_changed=True)`
(`src/sase/ace/tui/actions/rename.py:300`). Tag changes mutate in-memory tags,
invalidate the panel cache, and also call a full display rebuild
(`src/sase/ace/tui/actions/agents/_tagging.py:101`).

Necessity:
These do not require a disk reload. A full display rebuild is only necessary
when a tag change moves an agent between visible panels or a rename changes
group membership/width enough that row patching is unsafe.

Plan:
Use `_try_patch_agent_row()` for same-panel rename/tag display changes. When
tag panels are active, rebuild only the affected source and target panels.

### Revive And Archive

Current path:
Revive removes dismissed state, refilters cached agents, then calls
`schedule_revive_full_history_refresh()` so the archive row is reloaded and
selected (`src/sase/ace/tui/actions/agents/_revive_execution.py:140` and
`:350`). The code already has a helper to upsert restored artifact dirs into
the artifact index (`src/sase/core/agent_artifact_index_lifecycle.py:219`).

Necessity:
Some archive/revive flows legitimately need history because the row may be
outside the normal visible inbox. But immediate UI restoration does not always
need a full-history source scan if the revived artifact directory is known and
can be upserted/scanned directly.

Plan:
Split revive into two paths:

- same-session or artifact-dir-known revive: upsert targeted artifact dirs,
  targeted-scan revived rows, insert them into the visible list, and select one;
- archive repair/history revive: keep explicit full-history refresh when the
  artifact directory cannot be trusted or the archive query needs historical
  discovery.

### Agent Run Log Modal

Current path:
The run-log modal loads all agents to filter by CL and related metadata
(`src/sase/ace/tui/modals/agent_run_log_modal.py:34`).

Necessity:
This is a modal/history operation, not the normal Agents-tab refresh hot path.
It can remain lower priority, but it is still a full history-style query.

Plan:
Add a CL-scoped artifact-index query later so the modal does not call
`load_all_agents()` for every open.

### Entry Jump Hints And Panel Grouping

Current path:
Entering and exiting agents jump mode rebuilds the Agents display to add/remove
hint text (`src/sase/ace/tui/actions/navigation/_entry_jump_mode.py:104`).
Changing panel grouping is also structural and currently rebuilds the list.

Necessity:
These are UI-structural rebuilds, not disk reloads. They can remain full display
rebuilds until the row delta layer is stable.

Plan:
Eventually render jump hints as an overlay or visible-row patch rather than
forcing a list rebuild. Treat panel grouping changes as legitimate full display
rebuilds.

## Proposed Implementation Plan

### Phase 1 - Add Refresh Taxonomy Telemetry

Add trace fields and tests that distinguish:

- `tier2_full_history_scan`;
- `tier1_broad_visible_load`;
- `agent_delta_load`;
- `display_full_rebuild`;
- `display_panel_rebuild`;
- `display_row_patch`;
- `display_row_insert`;
- `display_row_remove`.

Include refresh source, full-history reason, changed artifact-dir count, agent
count, panel count, and whether the call landed during or immediately after a
launch.

Also add benchmark/repro coverage for the known gap from
`memory/long/tui_jk_baseline.md`: Agents-tab post-action flows, especially
launch followed by `j`.

### Phase 2 - Build A Targeted Agent Delta Service

Create a TUI-facing service, for example `AgentRefreshDelta`, that can represent:

- changed artifact dirs;
- inserted agents;
- updated agents;
- removed identities;
- changed workflow parent/child relationships;
- affected panel keys;
- fallback reason.

The service should reuse the current loader's domain pipeline where needed:
dead-PID filtering, deduplication, workflow overrides, dismiss/hide projection,
and sorting. For one-row deltas, use cached ChangeSpec data instead of loading
all ChangeSpecs unless the change is ambiguous.

Acceptance:

- Applying a delta to `_agents_with_children` produces the same final visible
  list as a broad Tier 1 load for focused fixture cases.
- Failed or ambiguous deltas return an explicit fallback reason and schedule the
  existing broad loader.

### Phase 3 - Expose Targeted Artifact Scan/Query

The Python lifecycle helper can upsert specific artifact dirs, but the normal
TUI loader API still queries active/recent/full-history sets. The Rust query
wire currently exposes `include_active`, `include_recent_completed`,
`include_full_history`, `active_limit`, `recent_completed_limit`, and
`include_hidden`, but not "these artifact dirs" or "these raw suffixes"
(`../sase-core/crates/sase_core/src/agent_scan/index.rs:44`).

Add one of:

- a Python/Rust facade for scanning a bounded list of artifact directories; or
- a targeted index query field for artifact dirs/raw suffixes.

Respect the backend boundary: shared artifact-index semantics belong in
`../sase-core`; TUI-only merge and display decisions stay in this repo.

### Phase 4 - Convert Launches To Delta Inserts

Use `AgentLaunchResult` as the launch delta seed:

- `_launch_background_agent()` returns `AgentLaunchResult`;
- TUI spawn callbacks return that result to `execute_launch_plan()`;
- multi-prompt/multi-model/bulk/repeat launch paths call an
  `apply_launch_result_delta()` callback per spawned slot;
- pre-launch broad refreshes are removed;
- the UI can show an optimistic STARTING row from reserved timestamp data, then
  targeted-reconcile it once the artifact directory exists.

Fallbacks:

- no result or no output path;
- targeted scan fails;
- current grouping/search mode cannot accept insertion yet;
- workflow fanout changes multiple parent/child relationships at once.

### Phase 5 - Convert Watcher Dirty Flags To Path Deltas

Keep `_dirty_agents` for fallback, but also store a coalesced set of changed
artifact dirs. Auto-refresh should prefer:

1. selected live-file panel refresh when only the selected file content changed;
2. artifact-dir delta for small relevant marker batches;
3. broad Tier 1 load for ambiguous/large/failed batches;
4. Tier 2 only for repair/fallback state or explicit full history.

### Phase 6 - Expand Incremental Display Operations

Add insertion and targeted panel rebuild support:

- `AgentList.insert_agent_row()` or a panel-level `update_list()` for one
  affected panel;
- row move when sorting/grouping changes but panel remains known;
- banner count updates for remove/insert;
- search-mode row removal;
- BY_DATE/BY_STATUS support;
- workflow parent/child tree deltas.

The first implementation can rebuild only affected panels when exact row insert
is too risky. That still avoids rebuilding every panel and all detail state.

### Phase 7 - Remove Redundant Filter/Search Loads

Change `_toggle_hide_non_run_agents()` and `_edit_agent_search_query()` so they
only refilter cached agents and refresh content-search state after first load.
Schedule a normal Tier 1 load only when the cached agent list has not been
loaded yet.

### Phase 8 - Split Revive Paths

Use targeted upsert/scan/insert when revive knows restored artifact dirs. Keep
`schedule_revive_full_history_refresh()` for archive search, missing artifact
dirs, index repair, or explicit history repair.

### Phase 9 - Verification

Add focused tests before removing broad refresh calls:

- TUI single-agent launch applies a launch delta and does not call
  `_load_agents_async`.
- Multi-prompt launch applies one delta per `AgentLaunchResult` and coalesces
  display work.
- One marker-file change updates only the affected row.
- Completion notification patches unread/completed state without broad reload
  when identity/artifact dir is known.
- Search/filter edits do not schedule `_schedule_agents_async_refresh` after
  first load.
- Dismiss/kill fast paths update banner counts and do not fall back under
  standard grouping.
- Fallback tests prove broad refresh still runs for ambiguous deltas and repair
  states.

Run the Agents-tab j/k latency repro around launch and post-action flows. The
target is no full visible-inbox load or all-panel OptionList rebuild in the
first navigation burst after a successful launch.

## Recommended Priority

1. Launch result propagation and targeted launch insert.
2. Watcher path-batched deltas for marker changes.
3. Filter/search redundant-load removal.
4. Incremental display panel rebuild/insert support.
5. Revive/archive split.
6. Run-log modal CL-scoped history query.

This order attacks the user-visible launch latency first and then removes the
largest steady-state dirty-refresh sources.

