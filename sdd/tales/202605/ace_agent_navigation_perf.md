---
create_time: 2026-05-13 12:19:46
status: done
prompt: sdd/prompts/202605/ace_agent_navigation_perf.md
---
# Plan - Make ACE Agents-Tab `j`/`k`/`J`/`K` Navigation Much Faster

## Context

The user profiled a real `sase ace --profile` session on May 13, 2026 and specifically felt lag while moving around
agent rows with `j`/`k` and switching agent panels with `J`/`K`. The profile file inspected for this plan is:

```text
.sase/home/tmp/sase/ace_profile_20260513_120957.txt
```

This plan is intentionally scoped to the ACE Python/Textual TUI. The repo guidance says presentation-only Textual state,
keybindings, layout, widget rendering, and Python glue belong here; no Rust-core change appears necessary for this work.

## What the profile says

The 28s profile includes about 20s waiting in `epoll`, so the useful signal is in the remaining UI-thread work. The
largest sampled costs relevant to this report are:

- `AceApp._run_agents_async_refresh` -> `_load_agents_async` -> finalize/apply: about 2.0s in the main sample.
- `finalize_agent_list`: about 1.05s, including:
  - `_sync_unread_completed_agents` -> `read_notification_snapshot`: about 0.44s.
  - `AgentDetail.refresh_current_file` -> `AgentFilePanel.refresh_file` -> diff-cache key/provider lookup: about 0.27s.
  - `_refresh_agents_display(list_changed=True)`: about 0.21s, with `AgentList.update_list`/OptionList rebuild around
    0.16s.
- Pure `j`/`k` samples are much smaller, but still visible:
  - `watch_current_idx` samples around 12-20ms.
  - `_refresh_panel_highlights` is often the largest per-key piece.
  - `_update_agents_info_panel` does repeated count/render work even when only the selected row changed.
  - `AgentDetail.update_display_immediate` is now header-only and cheap, which is good.

The important conclusion is that there are two overlapping problems:

1. Background/full refresh finalization still lands expensive work on the UI thread, so keystrokes queue when it
   overlaps navigation.
2. The hot navigation path is much better than before, but it still does more work per keypress than necessary,
   especially for panel focus changes and the info panel.

## Goal

Make `j`/`k` row navigation and `J`/`K` panel navigation feel instant on large agent lists, even while agent refreshes,
notification updates, and active-agent diff refreshes are happening in the background.

Target behavior:

- Pure `j`/`k` p95 key-to-paint under one frame budget on realistic large agent lists.
- `J`/`K` panel switching does not rebuild every agent panel.
- No notification snapshot read, VCS provider lookup, diff-cache key computation, full prompt render, or full OptionList
  rebuild runs on the direct navigation frame unless the list structure actually changed.
- Full refreshes still happen promptly after navigation pauses.

## Non-goals

- No keymap changes.
- No redesign of the Agents tab layout.
- No Rust-core migration for this pass.
- No optimistic insertion/reordering of newly launched agents.
- No broad rewrite of Textual widgets; keep the existing panel/list/detail architecture.

## Phase 0 - Establish a reliable local benchmark

Before changing behavior, extend the existing perf coverage so we can verify the real target:

- Add or extend a slow Pilot benchmark for the Agents tab with synthetic large lists, multiple tag panels, collapsed
  banners, and active statuses.
- Cover both `j`/`k` row navigation and `J`/`K` panel navigation.
- Capture p50/p95/max through the existing `SASE_TUI_PERF=1` JSONL path.
- Add targeted trace counters for:
  - `AgentList.update_list`
  - `AgentList.update_highlight`
  - `_refresh_agents_display(list_changed=True)`
  - `_refresh_panel_highlights`
  - `_update_agents_info_panel`
  - `AgentDetail.refresh_current_file`
  - notification snapshot reads

This gives us a baseline and prevents "fast in theory, still slow in real UI" fixes.

## Phase 1 - Stop refreshing files from agent-list finalization

The biggest avoidable UI-thread cost in the profile is the selected-agent file refresh inside `finalize_agent_list`.
That path calls `AgentDetail.refresh_current_file(selected_agent)` after
`_refresh_agents_display(..., defer_detail=True)`. For active agents this can compute diff cache keys, resolve VCS
providers, run plugin/workspace detection, and spawn background fetch plumbing. It is the wrong work to do as part of
list finalization, especially while the user is moving.

Change the model to:

- Full agent-list refresh updates the list and the cheap selected-agent header only.
- File/thinking/diff refresh starts only from the debounced detail update after navigation has been idle for the
  existing debounce window.
- If a non-navigation refresh wants to eagerly refresh the current file, route it through the same debouncer or a
  navigation-gated idle callback.
- Keep generation checks so stale file/thinking workers cannot update a no-longer-selected agent.

Acceptance tests:

- `finalize_agent_list(... on_agents_tab=True ...)` with `defer_detail=True` must not call
  `AgentDetail.refresh_current_file`.
- Holding `j`/`k` across N agents starts file/thinking/diff work only for the final selected agent after debounce.
- A full refresh while idle still eventually refreshes the selected agent detail.

## Phase 2 - Move notification snapshot reads out of the hot finalizer

`_sync_unread_completed_agents` reads the notification snapshot during agent finalization, and the profile shows this
can cost hundreds of milliseconds. That should not happen inside every agent-list finalization on the UI thread.

Change the model to:

- Maintain a cached notification snapshot/count state on the app.
- Refresh that cache from existing notification refresh paths, filesystem dirty flags, or an async worker.
- During agent finalization, use the cached snapshot only.
- If the cache is stale, schedule an async notification refresh and then patch unread markers/counts when it completes.

This keeps notification correctness while removing disk/Rust snapshot reads from the list finalization critical path.

Acceptance tests:

- Agent finalization must not call `read_notification_snapshot` directly.
- A notification refresh updates unread completed-agent state and patches affected rows.
- Startup still initializes unread state once the notification cache becomes available.

## Phase 3 - Make `J`/`K` panel focus changes a highlight-only operation

The current `action_focus_next_agent_panel` / `action_focus_prev_agent_panel` path changes focused panel, selects a row,
then calls `_refresh_agents_display(list_changed=True)`. That rebuilds every panel even though the agent list did not
change. The user explicitly included `J`/`K`, so this is a high-value fix.

Change the model to:

- After changing `_panel_group.focused_idx` and selecting the first/last stop in the target panel, call a focused-panel
  refresh path, not a full list rebuild.
- That path should:
  - update `-focused-panel` classes on only the old and new panel widgets,
  - move the highlight in the focused panel,
  - focus the new panel widget,
  - update the info panel in navigation mode,
  - schedule the normal debounced detail update.
- Keep full rebuilds only for structural changes: tags/panels changed, grouping mode changed, folds changed, search
  changed, list contents changed.

Acceptance tests:

- 50 `J`/`K` panel switches call `AgentList.update_list` zero times.
- Panel focus classes and highlighted row remain correct after wraparound.
- Banner/group focus still works when the first/last stop is a collapsed banner.

## Phase 4 - Add a navigation-only info-panel update path

`_update_agents_info_panel` currently recomputes visible top-level counts and calls several `AgentInfoPanel.update_*`
methods. Each method rebuilds the Rich text. During pure navigation, most of those values are unchanged.

Change the model to:

- Split info-panel updates into:
  - full metric recomputation for list/notification/search/grouping changes,
  - navigation-only update for selected position and view mode.
- Store metric counts in a cached snapshot keyed by agent-list identity, unread-version, grouping/search state, and
  panel mode.
- Add an idempotent/batched `AgentInfoPanel.update_state(...)` or equivalent so one logical update triggers one Static
  render, not several.
- On `j`/`k`, avoid rescanning all visible top-level agents unless selecting an unread completed agent changes the
  unread counts.

Acceptance tests:

- 100 `j`/`k` moves over unchanged agents do not recompute status counts 100 times.
- `AgentInfoPanel._update_display` is called at most once per navigation frame.
- Unread acknowledgement still decrements unread counts and patches row styling.

## Phase 5 - Tighten the row-navigation hot path

The cached navigation stops are good, but each key still scans the stops list to find the current position. This is
small in the profile but easy to make robust for large trees.

Change the model to:

- Extend the `_panel_navigation_stops` cache to include reverse maps:
  - agent index -> stop position
  - banner group key -> stop position
- Use those maps in `_navigate_agents_panel`, `_capture_focused_visible_pos`, and related restoration paths.
- Preserve the existing nearest-anchor fallback for stale keys/indices.

Acceptance tests:

- A 1,000-stop synthetic navigation burst does not linearly scan stops on every key.
- Existing banner and nearest-anchor reliability tests still pass.

## Phase 6 - Keep full refreshes off the navigation frame

Some of this already exists: `_run_agents_async_refresh` consults `NavigationGate`, and launch fan-out can use
`request_agents_refresh`. Keep that model and close gaps found while implementing Phases 1-5.

Audit all paths that can call `_refresh_agents_display(list_changed=True)` or `_schedule_agents_async_refresh` while the
user is navigating:

- notification actions,
- unread acknowledgement,
- dismiss/kill optimistic updates,
- panel grouping/folding,
- launch fan-out,
- filesystem watcher events,
- auto-refresh.

The rule is:

- Direct user actions that structurally change the list may rebuild immediately.
- Background refreshes and incidental side effects must either patch rows or defer until the navigation gate is idle.
- Selecting a different row/panel never performs a full list rebuild.

Acceptance tests:

- Synthetic j/k burst overlapping a scheduled agents refresh does not run apply/finalize/display until idle.
- Unread acknowledgement prefers row patching; full refresh fallback is gated/deferred if possible.
- Dismiss/kill fast paths still preserve selection and panel focus.

## Phase 7 - Verification

Run focused tests first, then the repo checks:

```bash
just install
pytest tests/ace/tui/test_agent_jk_navigation.py \
  tests/ace/tui/test_jk_reliability.py \
  tests/ace/tui/test_post_launch_jk_lag.py \
  tests/ace/tui/test_agents_refresh_coalescing.py \
  tests/ace/tui/test_event_handlers_dirty_flags.py \
  tests/ace/tui/test_agent_detail_two_phase.py \
  tests/ace/tui/widgets/test_agent_list_row_lookup.py
pytest -s -m slow tests/ace/tui/bench_tui_jk.py
just check
```

If the slow benchmark is too noisy for a hard assertion, keep it as a before/after report and use deterministic unit
tests for structural guarantees like "no update_list during j/k/J/K".

## Implementation order

1. Add benchmark/counters for Agents-tab `j`/`k` and `J`/`K`.
2. Remove selected-file refresh from `finalize_agent_list`; route it through debounced detail.
3. Cache/asynchronously refresh notification snapshots instead of reading them in finalization.
4. Make `J`/`K` panel focus changes highlight-only.
5. Split and batch info-panel updates.
6. Add reverse maps to the navigation-stops cache.
7. Audit remaining full-refresh callers and gate/defer background ones.

This order attacks the largest profile costs first, then removes the remaining per-key waste.
