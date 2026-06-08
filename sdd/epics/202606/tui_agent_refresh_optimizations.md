---
create_time: 2026-06-08 14:05:44
bead_id: sase-4f
tier: epic
status: done
prompt: sdd/prompts/202606/tui_agent_refresh_optimizations.md
---
# Plan: Remove Avoidable Full Agents-Tab Refreshes

## Objective

Implement the consequential optimizations recommended by `sdd/research/202606/agents_tui_full_refresh_audit.md`, with
each phase sized for a separate agent instance. The goal is to keep full Agents-tab refreshes for first load, explicit
manual repair/history paths, and true structural fallbacks, while removing them from common launch, watcher,
notification, and local mutation paths.

## Validated Findings Used By This Plan

The following findings were checked against the current code before planning:

- Launch result propagation is the top priority. `spawn_agent_subprocess(...)` returns `AgentLaunchResult`, and
  `execute_launch_plan(...)` preserves it in `LaunchExecutionRecord.result`, but the TUI bridge
  `src/sase/ace/tui/actions/agent_workflow/_launch_background.py` returns `None`. Single and repeat launch spawn
  callbacks therefore discard the result.
- Launch hot paths still request broad Agents refreshes: `_launch_body.py` schedules a refresh after single/workflow
  dispatch, `_launch_multi_prompt.py` and `_launch_multi_model.py` request refreshes before/during/after fan-out,
  `_launch_repeat.py` requests refresh per slot, and `_launch_bulk.py` requests refresh per spawned CL.
- `_load_agents_async(...)` already moves disk/index work off the UI thread, but finalization still installs a full list
  and calls `_refresh_agents_display(list_changed=True, defer_detail=True)` on the Agents tab. Narrow data reads alone
  will not fix display rebuild cost.
- The display layer can patch changed rows and remove rows (`_try_patch_agent_row`, `_try_remove_agent_rows`,
  `AgentList.patch_agent_row`, `AgentList.try_remove_rows`) but has no supported insert/move path. Textual `OptionList`
  exposes add/remove/replace/reset APIs, but no supported indexed insert API.
- `sase-core` already has an internal exact `scan_agent_artifact_dir(...)`, used by index upsert, but the Python
  binding/facade and TUI loader do not expose a batch exact-artifact delta read. `AgentArtifactIndexQueryWire` can query
  active/recent/full-history sets, not "these artifact dirs changed".
- The watcher maps path changes to surface dirty flags and known marker names, then `_on_auto_refresh` still calls
  `_load_agents_async(source="auto_refresh")` when Agents are due. It does not retain exact artifact-dir deltas.
- STARTING polling detects marker signature changes, but its only current response is
  `request_agents_refresh("starting_poll")`.
- Notification projection already patches some visible rows, but several modal and status paths still call
  `request_notification_agents_refresh(...)`, which falls through to a coalesced broad Agents refresh.
- Filter/search already has `_refilter_agents()` for cached in-memory filtering, but public actions still schedule
  `_schedule_agents_async_refresh(source="filter")` after refiltering.
- Rename/tag/mark/unread/revive have local memory mutations and some row patch paths, but still often fall back to
  all-panel display rebuilds or full-history reloads.

## Guardrails

- Keep broad Tier 1 reload and Tier 2 full-history refresh as explicit fallbacks with named reasons. Do not silently
  remove repair behavior.
- Do not hand-roll backend domain behavior in Python if another frontend would need the same behavior. Cross-frontend
  artifact scan/query behavior belongs in `sase-core`; open the matching numbered workspace with
  `sase workspace open -p sase-core <workspace_num>` before editing it.
- Do not assume Textual supports indexed insertion. The first display win should be affected-panel rebuild plus existing
  row patch/remove. True insertion can be isolated later behind tests.
- Preserve navigation-gate behavior from `tests/ace/tui/test_post_launch_jk_lag.py`. No phase should reintroduce
  UI-thread work during a j/k burst.
- Every implementation phase must run targeted tests and `just check` after file changes. Run `just install` first if
  the workspace has not been initialized.

## Phase 1: Refresh Telemetry And Fallback Classification

Purpose: make every later phase measurable and safe to validate.

Deliverables:

- Add structured trace fields or helper wrappers for Agents refresh work: source, data cost, display cost, and fallback
  reason.
- Classify the three costs independently: `tier2_full_history`, `tier1_broad_load`, `artifact_delta_load`,
  `display_full_rebuild`, `display_panel_rebuild`, `row_patch`, `row_remove`, `row_insert`.
- Add fallback reasons for common gates: missing launch result, missing artifact dir, delta read failure, active search,
  unsupported grouping, width growth, panel membership change, workflow tree change, dirty queue overflow, unknown
  watcher path, persistence error.
- Add regression tests that can assert broad launch refreshes disappear in later phases without relying on log text.

Likely files:

- `src/sase/ace/tui/actions/agents/_loading_refresh.py`
- `src/sase/ace/tui/actions/agents/_loading_disk.py`
- `src/sase/ace/tui/actions/agents/_loading_finalize.py`
- `src/sase/ace/tui/actions/agents/_display.py`
- `src/sase/ace/tui/actions/agents/_display_panel_patches.py`
- `tests/ace/tui/test_agents_refresh_coalescing.py`
- `tests/ace/tui/test_post_launch_jk_lag.py`

Acceptance checks:

- Existing refresh behavior is unchanged except trace metadata.
- Tests can distinguish a launch delta from `_load_agents_async(source="launch")`.
- Navigation-gate tests still prove refreshes defer during j/k bursts.

## Phase 2: Exact Artifact Delta Read API

Purpose: provide a shared way to load a bounded set of known artifact dirs through the same scanner-shaped records used
by full loads.

Deliverables:

- In `sase-core`, expose a Python binding for exact artifact-dir scanning, either: a batch API over the existing
  internal `scan_agent_artifact_dir(...)`, or an exact-artifact filter on the index query. Prefer a batch API returning
  `AgentArtifactScanWire` because watcher/launch paths naturally produce dirs.
- Add Python facade records/conversion support in `src/sase/core/agent_scan_facade.py`.
- Add a TUI-facing delta loader that accepts artifact dirs, updates/upserts the artifact index when appropriate, and
  returns normalized `Agent` values through the existing loader pipeline: dead-PID filtering, deduplication, workflow
  child overrides, dismissed/hide projection, ordering, status overrides, and content-search cache invalidation.
- Keep a broad Tier 1 load fallback when a delta cannot be scanned, cannot be normalized, or implies repair/history
  recovery.

Likely files:

- `../sase-core/crates/sase_core/src/agent_scan/*`
- `../sase-core/crates/sase_core_py/src/lib.rs`
- `src/sase/core/agent_scan_wire_records.py`
- `src/sase/core/agent_scan_wire_conversion.py`
- `src/sase/core/agent_scan_facade.py`
- `src/sase/ace/tui/models/agent_loader.py`
- `src/sase/ace/tui/actions/agents/_loading_disk.py`

Acceptance checks:

- Unit tests cover missing dirs, invalid dirs, visible hidden rows, exact project/workflow filters, marker signature
  repair, and duplicate dirs.
- A TUI delta load can return one running/done/waiting/question/workflow child agent without walking or querying the
  full visible inbox.
- Existing full load tests still pass.

## Phase 3: Agents Display Diff And Affected-Panel Rebuild

Purpose: avoid all-panel rebuilds after narrow data changes even before true indexed insertion exists.

Deliverables:

- Add an identity-based display diff that compares the previous and next `_agents` lists after finalization and
  classifies: changed same-position rows, removals, additions, moves, and structural changes.
- Apply existing row patch/remove paths first.
- Add an affected-panel rebuild helper that calls `AgentList.update_list(...)` only for panels whose membership/content
  changed, updates panel titles/heights, and refreshes focus/detail/info consistently.
- Keep full display rebuild fallback for active search, unsupported grouping, width growth, workflow tree ambiguity,
  panel collection changes, and any failed patch/panel rebuild.
- Do not implement Textual internals-based indexed insertion in this phase unless it is demonstrably simpler than
  affected-panel rebuild and is covered by focused widget tests.

Likely files:

- `src/sase/ace/tui/actions/agents/_display.py`
- `src/sase/ace/tui/actions/agents/_display_panel_refresh.py`
- `src/sase/ace/tui/actions/agents/_display_panel_patches.py`
- `src/sase/ace/tui/widgets/agent_list.py`
- `src/sase/ace/tui/widgets/_agent_list_build.py`
- `tests/ace/tui/test_agent_panels_display.py`
- `tests/ace/tui/widgets/test_agent_list_try_remove_rows.py`
- new tests for affected-panel rebuild behavior

Acceptance checks:

- Single-row mutations patch rows without all-panel rebuild.
- Single-panel additions/removals rebuild only that panel.
- Multi-panel membership changes rebuild affected panels or fall back with a named reason.
- Full rebuild remains available and tested.

## Phase 4: Launch Delta Conversion

Purpose: remove the biggest hot-path broad refresh: agent launch.

Deliverables:

- Change `_launch_background_agent(...)` to return `AgentLaunchResult`.
- Change all TUI spawn callbacks passed to `execute_launch_plan(...)` to return that result, so
  `LaunchExecutionRecord.result` is populated for single and repeat launches.
- Add a common TUI launch-delta handler that accepts one or more `AgentLaunchResult` values, derives artifact dirs from
  `output_path`, seeds optimistic STARTING rows only when identity/order can match the loader, and schedules an exact
  artifact-dir reconcile through Phase 2.
- Convert single, multi-prompt, multi-model, repeat, and bulk launch to use the common handler. Remove pre-launch
  `request_agents_refresh("launch")` calls once user feedback is represented by toast/progress/optimistic rows.
- Keep broad launch refresh fallback for missing result, missing artifact dir, delta scan failure, active
  search/grouping that cannot safely display the delta, workflow parent/child structural reshapes, and partial-launch
  rollback.

Likely files:

- `src/sase/ace/tui/actions/agent_workflow/_launch_background.py`
- `src/sase/ace/tui/actions/agent_workflow/_launch_body.py`
- `src/sase/ace/tui/actions/agent_workflow/_launch_multi_prompt.py`
- `src/sase/ace/tui/actions/agent_workflow/_launch_multi_model.py`
- `src/sase/ace/tui/actions/agent_workflow/_launch_repeat.py`
- `src/sase/ace/tui/actions/agent_workflow/_launch_bulk.py`
- `src/sase/agent/launch_executor.py`
- `src/sase/agent/launch_executor_types.py`
- `tests/ace/tui/test_agent_launch_dispatch.py`
- `tests/ace/tui/test_launch_fan_out_unified.py`
- `tests/test_agent_launch_repeat.py`
- `tests/ace/tui/test_agent_launch_non_blocking.py`

Acceptance checks:

- Successful single launch on the Agents tab does not call `_load_agents_async(source="launch")`.
- Multi-prompt/model/repeat/bulk launch batches result deltas and does not schedule one broad refresh per slot.
- Launch result fields are preserved in records and used for artifact-dir reconcile.
- Existing partial-launch rollback semantics remain unchanged.

## Phase 5: Watcher, STARTING Poll, And Notification Deltas

Purpose: convert exact external marker changes from dirty-flag broad loads to bounded artifact deltas.

Deliverables:

- Store a bounded queue/set of changed artifact dirs alongside `_dirty_agents`. Extract dirs from known marker paths in
  `_on_artifact_change(...)`.
- Route known small marker batches through the exact delta loader and display diff. Keep `_dirty_agents=True` and broad
  auto-refresh for unknown paths, root/project changes, queue overflow, directory moves/deletes that cannot be mapped
  safely, index repair signals, and persistence errors.
- Change STARTING polling to enqueue the changed agent artifact dir and invoke a targeted reconcile rather than
  `request_agents_refresh("starting_poll")` in the common path.
- Convert notification status/unread modal flows to patch visible rows first and request a broad Agents refresh only
  when the notification cannot be resolved to an in-memory visible identity/artifact dir.

Likely files:

- `src/sase/ace/tui/actions/_event_refresh.py`
- `src/sase/ace/tui/actions/_state_init.py`
- `src/sase/ace/tui/actions/agents/_loading_refresh.py`
- `src/sase/ace/tui/actions/agents/_notification_utils.py`
- `src/sase/ace/tui/actions/agents/_notification_status_overrides.py`
- `src/sase/ace/tui/actions/agents/_notification_modal_flow.py`
- `src/sase/ace/tui/actions/agents/_notification_modals.py`
- `src/sase/ace/tui/actions/agents/_notification_question_modal.py`
- `tests/ace/tui/test_event_handlers_dirty_flags.py`
- `tests/ace/tui/test_starting_agent_poll.py`
- `tests/ace/tui/test_agent_notification_status_overrides.py`
- `tests/ace/tui/test_agent_unread_projection.py`

Acceptance checks:

- Known marker writes enqueue exact artifact dirs and do not broad-load when the batch is under the limit.
- Unknown paths and overflow still trigger broad fallback with named reasons.
- STARTING to RUNNING/WAITING/DONE transitions patch or affected-panel rebuild without broad load in the common path.
- Notification completion/unread/plan/question changes patch rows when possible.

## Phase 6: Display-Only And Local Mutation Cleanups

Purpose: remove remaining broad reloads/rebuilds from local actions whose data is already in memory.

Deliverables:

- Filter/search: after first load, call `_refilter_agents()` and refresh the content-search index without scheduling
  `_schedule_agents_async_refresh(source="filter")`. Preserve the initial-cache fallback inside `_refilter_agents()`.
- Rename: after writing `agent_meta.json` and updating the index, mutate the in-memory agent and patch same-panel rows
  or rebuild affected panels. Fall back only when sort/group membership changes require it.
- Tagging: patch same-panel tag rendering when membership is unchanged, rebuild source/target panels when tag-panel
  membership changes, and avoid all-panel rebuilds for simple tag text changes.
- Marking/unread: batch patch visible affected rows for clear marks and mark-all-read instead of all-panel rebuilds.
- Revive: when revived artifact dirs are known, upsert/scan/insert via the delta loader and affected-panel rebuild. Keep
  full-history refresh for archive discovery, missing dirs, and explicit recovery.
- Optionally convert entry jump hints to visible-row patching/overlay if they still appear in traces as a material cost.

Likely files:

- `src/sase/ace/tui/actions/agents/_filter_actions.py`
- `src/sase/ace/tui/actions/rename.py`
- `src/sase/ace/tui/actions/agents/_tagging.py`
- `src/sase/ace/tui/actions/agents/_marking.py`
- `src/sase/ace/tui/actions/agents/_unread.py`
- `src/sase/ace/tui/actions/agents/_revive_execution.py`
- `src/sase/ace/tui/actions/navigation/_entry_jump_mode.py`
- `tests/test_agents_tab_query_filter.py`
- `tests/ace/tui/test_agent_tagging.py`
- `tests/ace/tui/test_agent_marking.py`
- `tests/ace/tui/test_agent_unread_toggle.py`
- `tests/ace/tui/test_agent_unread_done_navigation.py`
- `tests/test_agent_revive.py`
- `tests/test_agent_group_revival_execution.py`

Acceptance checks:

- Filter/search after initial load does not schedule an async Agents refresh.
- Rename/tag/mark/unread common paths avoid all-panel rebuild and never reload from disk.
- Revive known-dir path uses delta loading; archive/custom discovery still uses full-history fallback.

## Cross-Phase Verification

Each phase should include focused unit tests plus a narrow subset of existing TUI tests around its surface. Before
considering the whole effort done:

- Run `just check`.
- Run `pytest -s -m slow tests/ace/tui/bench_tui_jk.py` and append comparable numbers to the baseline memory only with
  explicit user approval, because the memory file is protected by project instructions.
- Add or extend a launch-adjacent benchmark that proves single launch and fan-out launch do not trigger broad Agents
  reloads in the successful path.
- Manually verify `SASE_TUI_PERF=1 sase ace` around single launch, fan-out, notification completion, STARTING
  transition, filter/search, tag/rename, and revive.

## Expected End State

- Full refreshes remain for first load, manual refresh, manual full history, repair/reconcile, unknown watcher events,
  overflow, and complex structural fallbacks.
- Successful launches produce optimistic/targeted delta updates and exact-dir reconciles rather than broad launch
  refreshes.
- Watcher and STARTING poll paths update exact changed artifacts when possible.
- Notification and local mutation paths patch rows or rebuild only affected panels in the common case.
- Remaining full refreshes are visible in traces with explicit fallback reasons.
