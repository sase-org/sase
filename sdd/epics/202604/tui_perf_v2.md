---
create_time: 2026-04-28 18:44:34
status: done
bead_id: sase-12
prompt: sdd/prompts/202604/tui_perf_v2.md
---
# TUI Performance v2 — Phased Implementation Plan

## Background

Inspired by `sdd/research/202604/sase_perf_v2_research.md`. The architecture for async dismiss / launch / agent-reload is
mostly in place, but a few main-thread hot spots and overly-broad refreshes still cause perceptible hitches in the
Agents tab — especially under large agent lists, kill-all bursts, and rapid `j/k` navigation right after a launch.

The work is split into six phases. Each phase is **independently shippable**: ends with green tests and `just check`,
and a separate agent instance can pick up the next phase from the working tree alone. Phases 1–4 are the highest
leverage; phases 5–6 are normalization / regression-trap cleanup. Running them in order is recommended but the only hard
ordering constraints are noted below.

## Goals (acceptance, end-to-end)

- Kill (single + bulk + kill-all) does no notification or dismissed-set disk I/O on the UI thread.
- Kill-all is one optimistic UI transaction with one persistence worker (one refresh, one notification rewrite), even
  for tens of agents.
- `j/k` after navigating to a new agent updates the prompt header within one frame and does not block on artifact reads.
- Single dismiss / kill of a single agent in a 200-agent list does not rebuild every visible row in the focused panel.
- Launch fan-out (multi-prompt, multi-model, repeat, bulk) collapses into a single coalesced refresh after the spawn
  burst settles, regardless of which helper kicked it off.
- No legacy synchronous kill methods remain reachable from action paths.

## Phase 1 — Move kill notification I/O off the immediate path

### Scope

Mirror the dismiss-path async pattern on the kill path.

`src/sase/ace/tui/actions/agents/_killing.py`

- In `_do_kill_agent()`: drop `dismiss_notifications_for_agent(agent)` and `self._refresh_notification_count()` from the
  immediate stage.
- Capture `dismissed_snapshot = set(self._dismissed_agents)` at schedule time and pass it to
  `_run_kill_persistence_async`.
- In `_run_kill_persistence_async()`:
  - keep `persist_kill_side_effects` in `asyncio.to_thread`,
  - move `save_dismissed_agents(dismissed_snapshot)` to use the snapshot (not a fresh read of `self._dismissed_agents`),
  - add `await asyncio.to_thread(dismiss_notifications_for_agents, related)` where
    `related = _agents_related_to_kill(agent, snapshot)` (extract a small helper if it doesn't exist),
  - finish with `await self._refresh_notification_count_async()`.
- In `_do_bulk_kill_agents()`: drop the synchronous `self._refresh_notification_count()` after the in-memory refresh.
- In `_run_bulk_kill_persistence_async()`: after the worker returns, call
  `await self._refresh_notification_count_async()`.

### Supporting work

- Confirm a `_refresh_notification_count_async()` exists on the app; if not, add one that does the disk-touching part in
  `asyncio.to_thread` and the indicator update on the UI thread via `call_later`.
- `dismiss_notifications_for_agents` (plural) already exists in `_killing_utils.py`; verify and reuse — do not introduce
  a parallel helper.

### Tests (under `tests/`)

- `test_kill_immediate_does_no_notification_io`: patches `load_notifications`, `mark_dismissed`,
  `save_dismissed_agents`, `parse_project_file`, `delete_agent_artifacts` and asserts the kill immediate stage calls
  none of them.
- `test_kill_schedules_one_persistence_task`: asserts exactly one `_run_kill_persistence_async` task is scheduled per
  `_do_kill_agent` call and the agent is removed from `_agents` before the worker runs.
- `test_kill_persistence_refreshes_count_async`: drives the worker to completion and asserts
  `_refresh_notification_count_async` is awaited exactly once.
- `test_bulk_kill_no_sync_count_refresh`: assert `_refresh_notification_count` is **not** called synchronously in
  `_do_bulk_kill_agents`.

### Deliverables

- Code change above.
- Tests above, all green.
- `just check` clean.

### Risk / rollback

- Worker exception path already calls `_schedule_agents_async_refresh()`; keep it intact so a failed notification
  rewrite still self-heals.
- The dismissed-set snapshot must be captured **before** the optimistic in-memory mutation so re-entrant kills cannot
  corrupt it.

---

## Phase 2 — Route kill-all through `_do_bulk_kill_agents`

### Scope

`src/sase/ace/tui/actions/agents/_killing.py::_kill_and_dismiss_all_agents`

The current confirm callback loops over `killable` calling `_do_kill_agent` for each one, then
`_do_dismiss_all(dismissable)`. Replace with:

```python
def on_dismiss(confirmed: bool | None) -> None:
    if confirmed:
        self._do_bulk_kill_agents(killable, dismissable)
```

`_do_bulk_kill_agents` already handles the kill+dismiss split, the optimistic in-memory mutation, marks clearing, and a
single bulk-persistence worker.

### Supporting work

- Verify `_do_bulk_kill_agents` correctly handles `dismissable` even when `killable` is empty (already does, but cover
  with a test).
- Confirm `_do_dismiss_all` callers elsewhere are unaffected (it is still used for marked-dismiss-only flows).

### Tests

- `test_kill_all_uses_bulk_path`: spy on `_do_bulk_kill_agents` and `_do_kill_agent`; assert one call to bulk, zero loop
  calls to single.
- `test_kill_all_single_refresh`: spy on `_refresh_agents_display` and assert it's called once after the confirm.
- `test_kill_all_only_dismissable`: empty `killable`, non-empty `dismissable` — bulk path still triggered, dismissed
  agents disappear.

### Deliverables

- One file change, ~10 lines.
- Tests above.
- `just check` clean.

### Dependency

Independent of Phase 1, but lands cleaner after Phase 1 because the bulk persistence path is the one whose async
behavior was just hardened.

---

## Phase 3 — Make `update_display_immediate` truly header-only

### Scope

`src/sase/ace/tui/widgets/prompt_panel.py` (or wherever `AgentPromptPanel` lives) and
`src/sase/ace/tui/widgets/agent_detail.py`.

- Add `AgentPromptPanel.update_header_only(agent)` that builds **only** the header text + any inline error traceback
  (cheap, in-memory) and renders via `self.update(...)`. Must not touch the artifact cache, must not call `os.listdir` /
  `os.stat` / read prompt or reply files.
- Change `AgentDetail.update_display_immediate` to call `prompt_panel.update_header_only(agent)` instead of
  `prompt_panel.update_display(agent)`.
- Leave the debounced `_fire_debounced_detail_update` path (and its full `update_display`) untouched — it stays the
  source of truth for prompt body, reply, thinking, file, diff content.

### Supporting work

- Audit `build_header_text` / equivalent for any sneaky disk reads (workflow metadata loads). If any exist, gate them
  behind a `cheap=True` flag and fall back to a generation-based skip.
- Guard the immediate path: `_agent_detail_generation` increments must still bump so any in-flight debounced worker
  discards its result correctly.

### Tests

- `test_update_display_immediate_does_no_io`: patch `artifact_cache.read_*`, `os.listdir`, `os.stat`, prompt artifact
  loaders; assert immediate path triggers zero disk reads.
- `test_update_display_immediate_does_not_call_full_panel_update`: spy on `AgentPromptPanel.update_display`; assert it
  is not called from the immediate path.
- `test_jk_navigation_uses_header_only`: simulate `j` keypress, assert the immediate stage uses the header-only API and
  the debounced full update fires after the debounce window.

### Deliverables

- Header-only API on `AgentPromptPanel`.
- Wired into `AgentDetail.update_display_immediate`.
- Tests above.
- `just check` clean.

---

## Phase 4 — Incremental row-removal fast path

### Scope

Avoid rebuilding the whole `AgentList` for a single optimistic remove.

`src/sase/ace/tui/widgets/agent_list.py`

- Add `AgentList.try_remove_rows(removed_identities: set[AgentIdentity]) -> bool`. Returns `True` if every removal could
  be applied in place (in textual, `OptionList.remove_option_at_index` per row, then update banner counts as needed);
  `False` if any condition makes the in-place path unsafe — caller must fall back.

`src/sase/ace/tui/actions/agents/_killing.py` and `_dismissing.py`

- Replace the unconditional `_refresh_agents_display(list_changed=True, ...)` inside `_apply_killed_agents_in_memory`
  (and the dismiss equivalent) with:
  1. Try `_try_remove_agent_rows(removed)` (a thin app-level wrapper).
  2. If `True`, only fire the lightweight focus restore + keybinding-footer refresh and skip the full rebuild.
  3. Else fall back to the current `_refresh_agents_display(...)`.

### Conservative gating (all must hold for fast path)

- `current_tab == "agents"`.
- No active agent search query.
- Grouping mode is `STANDARD` (or any mode where banner counts/order would not need recomputation — keep the gate
  strict; expand later).
- All removed identities reside in a single panel.
- No removed agent is a workflow parent with visible folded children.

### Tests

- `test_single_dismiss_uses_fast_path`: 200 agents, dismiss one DONE leaf; assert `AgentList.update_list` is **not**
  called and the dismissed row is gone from the option list.
- `test_single_kill_uses_fast_path`: same but for a top-level RUNNING agent.
- `test_fast_path_falls_back_under_search`: with a search query active, assert the full refresh path is taken.
- `test_fast_path_falls_back_for_workflow_parent`: dismissing a workflow parent triggers full rebuild (children removal
  needs recount).
- `test_focus_visually_below_killed`: focus restoration still lands on the agent visually below the removed one
  (regression guard for existing behavior).

### Deliverables

- New `try_remove_rows` API + wrapper.
- Updated `_apply_killed_agents_in_memory` and dismissal twin.
- Tests above.
- `just check` clean.

### Risk / rollback

- The conservative gate means the fall-back path is the existing, battle-tested one. If any reliability regression
  appears, set the gate to always return `False` to disable the fast path with a one-liner.

---

## Phase 5 — Unify launch fan-out + source-aware refresh coalescing

### Scope

Make multi-prompt / multi-model / repeat / bulk launch behave like single launch: one worker model, one coalesced
refresh.

Files: `src/sase/ace/tui/actions/agent_workflow/*.py` (the fan-out helpers that currently use `threading.Thread(...)`
directly), the launch-context plumbing in `_finish_agent_launch` / `_run_agent_launch_body_async`, and the refresh
scheduler (`_schedule_agents_async_refresh` / equivalent).

- Replace `threading.Thread(target=..., daemon=True).start()` fan-out call sites with `asyncio.to_thread` (or Textual
  `run_worker`) so the single- launch and fan-out paths use the same worker model.
- Snapshot `self._prompt_context` / launch context on the UI thread before handing to the worker. The worker should not
  read or mutate UI-owned state directly; it returns a result the UI thread commits via `call_later`.
- Introduce `request_agents_refresh(source: str, debounce_ms: int = 150, latest_only: bool = True)` over the existing
  scheduler. All fan-out spawn paths call this with `source="launch"` instead of scheduling a refresh per-agent. The
  scheduler collapses bursts within the debounce window into a single deferred refresh, still gated by `NavigationGate`.

### Tests

- `test_multi_prompt_launch_single_refresh`: spawn 5 agents through multi-prompt; assert
  `_schedule_agents_async_refresh` (or whatever the unified call becomes) fires exactly once after the burst settles.
- `test_launch_fan_out_uses_asyncio_to_thread`: assert no raw `threading.Thread` instances are created from the launch
  helpers (mock / spy on the constructor).
- `test_launch_context_is_immutable_snapshot`: mutate the UI's `_prompt_context` after a launch worker has been
  dispatched; the worker's view of the context is unaffected.
- `test_launch_refresh_respects_navigation_gate`: hold the gate during the burst, assert the coalesced refresh defers
  until release.

### Deliverables

- Unified launch worker model.
- Source-aware coalescing helper.
- Tests above.
- `just check` clean.

### Dependency

Independent of phases 1–4; can be done in parallel by a different agent. Conflict surface is small (fan-out helpers +
scheduler).

---

## Phase 6 — Quarantine legacy synchronous kill handlers

### Scope

`src/sase/ace/tui/actions/agents/_kill_type_handlers.py`

- Remove the synchronous per-type kill methods that parse/update project files, release workspaces, save bundles, delete
  artifacts, and persist dismissed agents inline — assuming all action paths route through `_do_kill_agent` /
  `_do_bulk_kill_agents` (as the research and current reading confirm).
- If any single call site still depends on a method, convert that method into a thin wrapper around the modern
  optimistic async path (or migrate the call site directly).

### Verification

- `git grep` for each removed symbol returns no production references.
- All existing kill-related tests still pass without modification.

### Tests

- `test_no_legacy_sync_kill_handlers_referenced`: a code-search-style guard test that asserts the removed names aren't
  reachable from `AgentKillingMixin` MRO.

### Deliverables

- Dead code removed (or wrappers, if any caller survived).
- Guard test.
- `just check` clean.

### Dependency

Lands after Phase 1 (which strengthens the modern async kill path) so we are sure the wrappers we remove have no
behavioral compensation needed.

---

## Cross-phase concerns

- **Tracing.** Use the existing `tui_trace(...)` spans on any new immediate- stage / worker boundaries so future
  regressions are observable in the same logs.
- **Navigation gate.** All async refreshes scheduled from kill / launch persistence workers must continue to honor
  `NavigationGate`. New refresh paths added in phases 1, 2, and 5 must be checked against this rule.
- **Dismissed-set snapshotting.** Phases 1 and 2 both touch the dismissed set. The rule: capture the snapshot on the UI
  thread before any optimistic mutation; the worker writes the snapshot, never re-reads `self._dismissed_agents`.
- **No new synchronous disk I/O on UI thread.** Any new code path that loads notifications, parses project files, reads
  artifacts, or writes dismissed-agents storage must be inside `asyncio.to_thread` or a Textual worker.

## Suggested execution order

1. Phase 1 (kill notification I/O off main thread) — highest impact, smallest blast radius.
2. Phase 2 (kill-all → bulk) — trivial after Phase 1.
3. Phase 3 (header-only immediate detail) — independent, big perceptual win.
4. Phase 4 (incremental row removal) — independent; benefits scale with list size.
5. Phase 5 (launch fan-out unification) — independent; can run in parallel with 3 / 4.
6. Phase 6 (legacy handler cleanup) — last, after the modern path is fully proven.

## Out of scope

- Replacing Textual / OptionList rendering wholesale.
- Notification system rewrite.
- Persistence-layer schema changes.
- Any change to the workspace-claim or retry-chain protocols.
