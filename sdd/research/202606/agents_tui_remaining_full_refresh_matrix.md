# Agents TUI Remaining Full Refresh Matrix

Status: Research
Date: 2026-06-08

## Scope

This note audits remaining Agents-tab refresh paths and classifies which full refreshes are still necessary. It is additive to:

- `sdd/research/202606/agents_tui_full_refresh_audit.md`
- `sdd/research/202606/incremental_agent_refresh.md`

No performance fixes were implemented as part of this research.

## Terms

"Full refresh" can mean three different costs in this codebase:

- Full history source scan: Tier 2 load of all agent artifact history, usually `full_history=True`.
- Broad visible-inbox reload: Tier 1 load through the artifact index or bounded fallback, still rebuilding the in-memory agent collection.
- Full display rebuild: `list_changed=True`, panel/list widget rebuilds, and `AgentList.build_list(...)`.

The slow launch/j-k regression is mostly caused by broad reloads and full display rebuilds on hot Agents-tab paths, not by explicit full-history refresh alone.

## Executive Conclusion

Full refreshes remain necessary for first load, manual refresh, explicit full-history repair, startup recovery, structural filter/grouping changes, and ambiguous large filesystem bursts. They are not inherently necessary for most known single-artifact mutations, especially launches, marker updates, notification unread projection, rename/tag changes, and many revive cases.

The main missing primitives are:

- An insert/update/remove display diff layer. Row patch and row removal already exist; row insertion does not.
- A targeted artifact-delta loader. The local facade can upsert one artifact dir, but the query/scan wire API does not expose exact artifact-dir batches.
- Launch result propagation back to the TUI. `spawn_agent_subprocess(...)` returns an `AgentLaunchResult`, but `_launch_background_agent(...)` discards it.
- Better fallback taxonomy, so broad reloads happen only after a known targeted path fails.

## Refresh Stack

### Async Refresh Orchestration

Relevant files:

- `src/sase/ace/tui/actions/agents/_loading_refresh.py`
- `src/sase/ace/tui/actions/agents/_loading_disk.py`
- `src/sase/ace/tui/actions/agents/_loading_apply.py`
- `src/sase/ace/tui/actions/agents/_loading_finalize.py`

Key behavior:

- `request_agents_refresh(...)` coalesces bursty requests and defaults to `latest_only=True`.
- `_schedule_agents_async_refresh(...)` runs last-request-wins scheduling and records `source` plus `full_history`.
- `_run_agents_async_refresh(...)` nav-gates while j/k is active, then calls `_load_agents_async(...)`.
- `_load_agents_async(...)` eventually calls `load_agents_from_disk_with_state(...)`.
- `_apply_loaded_agents_prepared(...)` merges loaded state and calls `_finalize_agent_list(...)`.
- `_apply_finalize_plan(...)` and `finalize_agent_list(...)` call `_refresh_agents_display(list_changed=True, defer_detail=True)` when on the Agents tab.

Current scheduling is protective, but still broad: after a reload is admitted, the loader and display finalizer rebuild too much for many known mutations.

### Display Rebuild Layer

Relevant files:

- `src/sase/ace/tui/actions/agents/_display.py`
- `src/sase/ace/tui/actions/agents/_display_panel_refresh.py`
- `src/sase/ace/tui/widgets/agent_list.py`
- `src/sase/ace/tui/widgets/_agent_list_build.py`
- `src/sase/ace/tui/actions/agents/_display_panel_patches.py`

Current primitives:

- Full panel/list rebuild through `_refresh_agents_display(list_changed=True)`.
- Highlight-only refresh through `_refresh_agents_display(list_changed=False)` or `_refresh_agents_display_debounced(...)`.
- Existing row patch through `_try_patch_agent_row(...)`.
- Existing row removal through `_try_remove_agent_rows(...)`.

Missing primitive:

- Insert row or move row within a panel without rebuilding the whole panel.

Current patch limitations:

- `_try_patch_agent_row(...)` only patches an already displayed row.
- It cannot handle BY_STATUS panel grouping.
- It fails if rendered width grows beyond the current target width.
- `_try_remove_agent_rows(...)` only handles the current Agents tab, no active search, STANDARD grouping, and removals within one widget.

This explains why launch still falls back to a full display rebuild: a newly launched agent is an insertion, and insertion has no fast path.

## Loader And Artifact Index

Relevant files:

- `src/sase/ace/tui/models/agent_loader.py`
- `src/sase/core/agent_artifact_index_lifecycle.py`
- `src/sase/core/agent_scan_facade.py`
- `src/sase/core/agent_scan_wire_records.py`

Current capabilities:

- `load_tiered_agents(...)` can use the artifact index for active and recent completed artifacts.
- `AgentLoadState.needs_full_history_reconcile` only requires full-history repair when the visible inbox is incomplete, repair is recommended, or the fallback was truncated.
- `upsert_agent_artifact_index_artifacts(...)` can update exact artifact dirs.
- `update_agent_artifact_index_for_marker_mutation(...)` can update one artifact dir after a marker change.
- `upsert_agent_artifact_index_row(...)` exists in the facade.

Current gap:

- `AgentArtifactScanOptionsWire` and `AgentArtifactIndexQueryWire` do not expose exact artifact-dir or raw-suffix filters.
- The TUI can upsert exact changed dirs, but cannot then ask the scan/query layer for just those exact changed artifacts using a first-class batch query.

Result:

Known file changes still tend to become broad visible-inbox reloads.

## Call-Site Matrix

| Area | Current path | Is a full refresh necessary? | Removal plan |
| --- | --- | --- | --- |
| Startup first load | `startup.py` schedules `_run_agents_async_refresh(source="startup")` after first paint. | Yes. | Keep broad Tier 1 startup load. Preserve post-first-paint scheduling. |
| Manual refresh | `base.py::action_refresh` schedules a manual Agents refresh. | Yes. | Keep. This is an explicit user repair command. |
| Manual full history | `base.py::action_refresh_agents_full_history` sets `full_history=True`. | Yes. | Keep. This is an explicit full-history command. |
| Idle Tier 2 repair | `_maybe_trigger_idle_tier2_reconcile(...)` schedules full history only after idle threshold and pending repair state. | Yes. | Keep, but ensure targeted paths do not over-arm repair. |
| Single launch | `_launch_body.py` calls `_launch_background_agent(...)`, then schedules `_schedule_agents_async_refresh(...)`. `_launch_background_agent(...)` discards `AgentLaunchResult`. | No, usually avoidable. | Return `AgentLaunchResult`, build an optimistic agent row, insert into the visible model, upsert index for the new artifact dir, and schedule a narrow reconcile. Fall back to broad refresh only if launch result is missing or the insertion fails. |
| Multi-prompt launch | `_launch_multi_prompt.py` requests `"launch"` refresh before worker start, on every spawn, and at completion/error. | No, mostly avoidable. | Remove pre-launch refresh. Use each `LaunchExecutionRecord.result` for optimistic insertion. Completion should only reconcile failed/missing records. |
| Multi-model launch | `_launch_multi_model.py` requests `"launch"` refresh before worker start and on each spawn. | No, mostly avoidable. | Same as multi-prompt. Use per-slot launch result deltas. |
| Repeat launch | `_launch_repeat.py` schedules `"launch"` refresh for each executed slot. | No, mostly avoidable. | Batch launch results and apply insert deltas once per UI tick. |
| Bulk launch | `_launch_bulk.py` schedules `"launch"` refresh per launched CL. | No, mostly avoidable. | Batch insert deltas by worker drain interval. Reconcile only missing/failed records. |
| Filesystem marker changes | `_event_refresh.py` marks `_dirty_agents=True`; `_on_auto_refresh(...)` later calls `_load_agents_async(source="auto_refresh")`. | Sometimes. | For paths mapped to one artifact dir, upsert/query only that artifact and patch/insert/remove. Keep broad reload for unknown paths, root-level moves, large bursts, or index-repair signals. |
| STARTING poll | `_poll_starting_agent_transitions(...)` stats marker files and calls `request_agents_refresh("starting_poll")` on changes. | Usually no. | Convert marker transitions to targeted artifact updates. Patch visible rows. Keep broad fallback if the artifact is not in memory and no exact query exists. |
| Notifications | `request_notification_agents_refresh(...)` schedules `"notification"` reloads. Notification polling also has row patch support. | Often no. | Prefer notification snapshot projection, `_apply_notification_status_overrides(...)`, and `_try_patch_agent_row(...)`. Use broad reload only when notification references an artifact absent from memory or hidden by current filters. |
| Plan approval background | `_finish_plan_approval_background_work(...)` refreshes count, then requests notification Agents refresh. | Usually no. | Refresh counts and patch affected row status/unread state. Reconcile exact artifact if plan approval changes marker files. |
| Auto-dismiss plan response | `_auto_dismiss_external_plan_response(...)` may refilter and request notification refresh. | Sometimes. | Keep local in-memory dismiss/filter update. Use removal fast path when hidden. Broad refresh only when external state cannot be matched to an in-memory agent. |
| Filter actions | `_filter_actions.py` schedules `"filter"` refreshes; `_refilter_agents(...)` already reuses `_agents_with_children` when available. | No after initial load. | Route filter/search changes through `_refilter_agents(...)`. Schedule disk load only when there is no cached agent model. |
| Tab switch to Agents | `app.py` refilters, then if `_dirty_agents` schedules `"tab_switch"` refresh. | Sometimes. | If dirty paths are known, apply queued deltas before display. Keep broad reload after long inactivity, unknown events, or dirty queue overflow. |
| Dismiss | `_apply_dismissal_in_memory(...)` already tries row removal, then falls back to `_refilter_agents(...)`. | Only fallback. | Improve row-removal coverage: multi-panel removals, banner count updates, BY_STATUS support. Keep broad fallback for active search or structural grouping until diff layer supports it. |
| Kill | `_apply_killed_agents_in_memory(...)` already tries row removal, then falls back to full display rebuild. Error recovery schedules refresh. | Only fallback. | Same as dismiss. Patch lifecycle rows when killed agents remain visible; remove rows when hidden. |
| Revive | `_revive_execution.py` refilters and schedules `schedule_revive_full_history_refresh(...)`. | Partly. | Split revive into immediate targeted insertion using known revived artifact dirs plus delayed full-history repair only when hidden history/index repair is needed. |
| Rename | `_set_agent_name(...)` writes `agent_meta`, upserts index, mutates memory, then full display rebuilds. | Usually no. | Patch row when panel membership and width constraints hold. If sort/search position changes, use move/insert/remove diff. Fall back to affected-panel rebuild. |
| Tagging | `_tagging.py` updates tags, clears marks, invalidates panel cache, and full display rebuilds. | Usually no. | Patch affected rows for tag text changes. Rebuild only affected panels when tag grouping/filter membership changes. |
| Mark toggle | `_toggle_mark_agent(...)` patches one row and falls back to full display rebuild. | Only fallback. | Keep existing fast path, improve fallback reason logging. |
| Clear marks | `_clear_agent_marks(...)` full display rebuilds. | No. | Patch marked rows in batch and update info/detail. |
| Mark all unread completed as read | `_mark_all_unread_done_agents_read(...)` full display rebuilds. | No. | Batch patch affected unread rows and refresh notification count/info. |
| Jump to next unread | `_jump_to_next_unread_done_agent(...)` patches row unless panel/group change requires full display. | Sometimes. | Keep structural fallback. Add move/highlight-only path where panel membership is unchanged. |
| Entry jump mode | `_begin_agents_jump_mode(...)` and `_exit_entry_jump_mode(...)` full display rebuild to show/hide hint text. | No, but lower priority. | Replace with overlay or per-row hint patch. |
| Panel grouping toggle | `action_toggle_agent_panel_grouping(...)` full display rebuilds. | Yes. | Keep. Grouping changes the panel structure. |
| Detail mode toggles | `_panel_detail.py` calls `_refresh_agents_display()` without `list_changed`. | No full list rebuild. | Already acceptable. |
| Agent run log modal refresh | `agent_run_log_modal.py` loads agents to filter by CL. | Not hot path. | Consider targeted CL query later. Not launch/j-k critical. |

## Necessary Full Refreshes To Keep

Keep these broad refreshes:

- Startup first load.
- Explicit manual refresh.
- Explicit manual full-history refresh.
- Idle full-history repair after incomplete/truncated visible inbox state.
- Structural panel grouping changes.
- First filter/search action before `_agents_with_children` exists.
- Watcher overflow, unknown changed paths, root-level project/workflow changes, or ambiguous directory moves.
- Error recovery after persistence failures where the in-memory state may be stale.

These should be tagged with explicit source/reason names so telemetry can distinguish intentional broad refreshes from avoidable ones.

## Removal Plan

### Phase 1: Refresh Taxonomy And Telemetry

Add structured reasons around refresh admission and fallback:

- Scheduled source: `launch`, `auto_refresh`, `starting_poll`, `notification`, `filter`, `refilter`, `tab_switch`, `manual`, `manual_full_history`, `repair`.
- Cost class: `display_patch`, `display_rebuild`, `tier1_reload`, `tier2_full_history`.
- Fallback reason: `missing_agent`, `active_search`, `grouping_unsupported`, `width_growth`, `panel_membership_change`, `query_api_missing`, `dirty_overflow`, `unknown_path`.

This should make it possible to prove that launch no longer admits broad reloads in the common path.

### Phase 2: Targeted Artifact Delta Loader

Introduce a TUI-facing delta service that accepts exact artifact dirs or raw suffixes:

1. Upsert changed artifact dirs through the existing index lifecycle helpers.
2. Query or scan only those exact dirs.
3. Convert returned records into `AgentWithChildren` values using the same normalization path as the full loader.
4. Merge results into `_agents_with_children` and `_agents`.
5. Emit display operations: insert, update, remove, move, or affected-panel rebuild.

Core API gap to close:

- Add exact artifact-dir filters to the scan/query wire API, or add a separate exact-artifact batch endpoint.

### Phase 3: Display Diff Layer

Extend existing display primitives:

- Keep `_try_patch_agent_row(...)` for simple row updates.
- Keep `_try_remove_agent_rows(...)` for removal, then broaden it to multi-panel and BY_STATUS cases.
- Add row insertion for STANDARD grouping.
- Add row move within a panel.
- Add affected-panel rebuild as the middle fallback between row patch failure and full display rebuild.

Fallback order should become:

1. Patch/insert/remove exact rows.
2. Rebuild affected panel only.
3. Rebuild all Agents panels.
4. Reload from disk.

Current behavior often jumps from step 1 failure directly to step 3 or 4.

### Phase 4: Launch Optimistic Insertion

Launch is the highest-value path.

Implementation shape:

1. Change `_launch_background_agent(...)` to return the `AgentLaunchResult` from `spawn_agent_subprocess(...)`.
2. Ensure `_spawn_from_tui(...)` returns that result.
3. Use `LaunchExecutionRecord.result` in single, multi-prompt, multi-model, repeat, and bulk launch paths.
4. Build an optimistic in-memory agent from the launch result fields: `output_path`, `project_file`, `project_name`, `workflow_name`, `cl_name`, `timestamp`, `agent_name`, `workspace_dir`, `workspace_num`, and `pid`.
5. Insert into `_agents_with_children` and the visible panel model.
6. Upsert the artifact index for the new artifact dir.
7. Schedule a narrow reconcile for the launched artifact dir.
8. Schedule broad refresh only if result propagation fails, exact artifact reconcile fails, or display insertion cannot handle the current structural state.

The immediate pre-launch refreshes in multi-prompt and multi-model launch should be removed once optimistic insertion is available.

### Phase 5: Watcher And Poller Deltas

Convert known path changes into exact artifact deltas:

- `agent_meta.json`: patch name/status/tags/runtime fields.
- `running.json`, `waiting.json`, `done.json`: lifecycle/status transition patch or panel move.
- `pending_question.json`: question indicator patch.
- `workflow_state.json`, `plan_path.json`, `retry_state.json`: row/detail patch if visible, exact reconcile if not enough data is available.

Keep broad auto-refresh only for unknown path types, dirty queue overflow, large bursts, or path changes outside an artifact dir.

### Phase 6: Notification, Dismiss, Kill, Revive

Notifications:

- Prefer notification snapshot projection and row patching.
- Use exact artifact reconcile for newly referenced artifacts not present in memory.
- Avoid `request_notification_agents_refresh(...)` in common visible-row cases.

Dismiss/kill:

- Continue optimistic in-memory mutation.
- Broaden row-removal support.
- Rebuild affected panels before falling back to all panels or disk reload.

Revive:

- Use known revived artifact dirs for targeted insertion.
- Keep delayed full-history repair only to recover older hidden history or index inconsistency.

### Phase 7: Filter And Display-Only Actions

Filter/search:

- After first load, filter changes should call `_refilter_agents(...)` only.
- Avoid scheduling `"filter"` disk refresh when `_agents_with_children` exists.

Display-only actions:

- Replace clear marks, mark-all-read, and entry-jump hint rebuilds with batch row patches or overlays.
- These are lower priority than launch and watcher changes, but they are good cleanup once diff primitives exist.

## Verification Plan

Add tests and benchmarks that specifically cover Agents-tab post-action behavior:

- Launch one agent while focused on Agents tab; assert no broad `_load_agents_async(source="launch")` in the successful result path.
- Launch multi-prompt/multi-model batches; assert one batched visible update per UI tick, not one full reload per slot.
- Marker transition from STARTING to RUNNING/DONE; assert targeted patch or exact artifact delta.
- Filter/search after initial load; assert no disk reload.
- Rename/tag visible row; assert row patch or affected-panel rebuild, not disk reload.
- Dismiss/kill/revive; assert fast path plus documented fallback.
- j/k benchmark with launched-agent fixtures, as called out in `memory/long/tui_jk_baseline.md`.

Suggested benchmark extension:

- Reuse `SASE_TUI_PERF=1 sase ace`.
- Extend `tests/ace/tui/bench_tui_jk.py` or add a sibling slow benchmark for launch-adjacent Agents-tab actions.
- Capture p95 and max key-to-paint latency before and after launch, marker transition, dismiss, kill, and notification actions.

## Priority Order

1. Launch result propagation and optimistic insertion.
2. Exact artifact-dir delta loader.
3. Display insertion and affected-panel rebuild.
4. Watcher marker deltas and STARTING poll conversion.
5. Notification refresh conversion.
6. Filter/search load removal after first cache.
7. Rename/tag/clear-marks/entry-jump display-only cleanup.
8. Revive split into targeted insertion plus optional delayed full-history repair.

## Open Questions

- Should exact artifact-dir querying live in the Rust scan facade, the artifact index query wire API, or a TUI-only helper layered above current upsert/query calls?
- Should optimistic launch rows be marked as provisional until first marker reconcile, or should they use the normal STARTING lifecycle immediately?
- How much BY_STATUS/grouping support is required before row insertion can ship, versus falling back to affected-panel rebuild for non-STANDARD grouping?
- Should dirty watcher bursts preserve individual paths for later targeted reconcile, or collapse to broad reload after a small bounded queue?

## Bottom Line

The remaining full refreshes are not all bugs. Some are intentional repair and structural rebuild paths. The expensive avoidable class is known, local state changes being routed through broad reload and full list rebuild. Agent launch is the clearest case: the subprocess already returns enough information to insert a row optimistically, but that result is not propagated to the TUI, and the display layer cannot yet insert rows incrementally.
