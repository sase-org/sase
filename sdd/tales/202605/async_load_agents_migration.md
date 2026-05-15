---
create_time: 2026-05-14 21:44:39
status: done
prompt: sdd/prompts/202605/async_load_agents_migration.md
---
# Plan: Migrate synchronous `_load_agents()` call sites to async

## Goal

Eliminate every UI-thread call of `_load_agents()` listed in the `tui_blocking_audit.md` "High Severity #1" finding so
that disk I/O, ChangeSpec discovery, dismissed-agent merges, and apply/render no longer block the Textual event loop.

The existing async path (`AgentLoadingDiskMixin._load_agents_async()` in
`src/sase/ace/tui/actions/agents/_loading_disk.py`) is invoked through `_schedule_agents_async_refresh()`
(`src/sase/ace/tui/actions/agents/_loading_refresh.py:48-70`), which already provides:

- Idempotent scheduling (collapses concurrent triggers via `_agents_refresh_scheduled` / `_agents_refresh_pending`).
- `full_history=True` propagation through both the in-flight and pending refreshes
  (`_agents_refresh_scheduled_full_history`, `_agents_refresh_pending_full_history`).
- Navigation-gate re-arming so apply/render is deferred during a j/k burst.

This plan reuses that infrastructure rather than introducing a new wrapper.

## Non-goals

- The other High Severity items (agent-query content search, artifact discovery, workflow JSON, ChangeSpec RUNNING
  reread). Those are separate audit follow-ups.
- Changes to `_load_agents()` itself; it stays for tests and as the worker-resolved code path used by
  `_load_agents_async()`.
- Changes to `_apply_loaded_agents()` or finalize logic.
- Off-thread agent-query content search (separate item).

## Constraints and invariants we must preserve

1. **Selected-agent restoration.** Several callers expect `_load_agents()` to leave `_agents`, `_agents_with_children`,
   status overrides, and selection in a coherent state before later code reads them. The async path captures the
   post-await selection identity, so selection survives across the worker hop, but **synchronous code that runs
   immediately after the call cannot read the freshly-loaded list** — it has to be moved into a continuation that fires
   after the refresh completes, or be expressed via in-memory state mutation + an async refresh for disk reconcile.
2. **Status-override visibility.** All four `_notification_status_overrides.py` paths set
   `_agent_status_overrides[identity]` and call `_load_agents()` to surface the override on the visible row. Status
   overrides are already consulted during finalize, so an async refresh will pick them up. But the user must see the
   change immediately, not after `_run_agents_async_refresh()` waits for the navigation gate. Therefore: **mutate the
   override and trigger a `_refilter_agents()` first, then schedule the async disk reload for any other state that may
   have changed.**
3. **Hidden-row reveal/restore (notification jump).** The `_jump_to_agent_notification` path toggles
   `hide_non_run_agents` twice within a single user action (reveal → search → restore on no match). It needs both
   passes' effects to be visible to the subsequent loop in the same call. Without `_load_agents()`, we must replace the
   second-load read with a different lookup (search `_agents_with_children` / current `_agents`) that doesn't depend on
   the disk reconcile having finished.
4. **Revive selection.** `_do_revive_agent` / `_do_revive_agents` rely on the post-load list to drive
   `_select_revived_agent()` and `_refresh_agents_display(list_changed=True)`. They also pass `full_history=True`, which
   is critical because the artifact index may not yet show the just-restored bundle. The async path must keep
   `full_history=True` semantics and the selection step must run after the load finishes.
5. **Filter toggle / query edit.** `_toggle_hide_non_run_agents` and the query-edit `on_dismiss` callback change
   in-memory filter state that affects only what `_apply_loaded_agents_prepared` / `finalize_agent_list` produce. They
   have no consumers that need the disk read to complete synchronously — `_refilter_agents()` already does the in-memory
   pass on the cached `_agents_with_children` list.
6. **First-Agents-tab cold load.** `app.py:354-355` runs only when `_agents_with_children` is still empty. Replacing
   this with a schedule means the Agents tab paints empty (with the existing loading indicator) for one async pass. That
   is acceptable as long as the paint clearly signals loading; `on_mount`'s initial schedule already handles the normal
   cold-start case the same way.
7. **Plan-feedback override.** `_handle_plan_feedback_submitted` sets the agent override to "RUNNING" after the user
   submits feedback. Like the other override paths, the user must see the row flip to RUNNING immediately. The external
   file write (`plan_response.json`) is independent of the refresh.
8. **`_loading_filter._refilter_agents` fallback.** When `_agents_with_children` is empty, `_refilter_agents()` falls
   back to `_load_agents()`. This fallback fires from in-memory refilter paths that the user expects to reflect
   immediately. The right replacement is the same as the cold-load case: schedule an async refresh and rely on the
   loading indicator. We must ensure callers don't blow up reading an empty `_agents` list immediately afterward.

## Inventory of call sites

| #   | File:line                                                               | Caller                                      | Current behavior after `_load_agents()`                                                                                 |
| --- | ----------------------------------------------------------------------- | ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| 1   | `src/sase/ace/tui/app.py:354-355`                                       | First Agents-tab activation cold-load       | Switches tab and returns; relies on `_apply_loaded_agents` for initial paint.                                           |
| 2a  | `src/sase/ace/tui/actions/agents/_filter_actions.py:15`                 | `_toggle_hide_non_run_agents`               | Returns immediately.                                                                                                    |
| 2b  | `src/sase/ace/tui/actions/agents/_filter_actions.py:26`                 | Query-edit on-dismiss                       | Returns immediately.                                                                                                    |
| 3   | `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_submit.py:97`      | `_handle_plan_feedback_submitted`           | Followed by prompt-bar unmount + notification refresh. Override already mutated.                                        |
| 4a  | `src/sase/ace/tui/actions/agents/_notification_modal_flow.py:40`        | `_jump_to_agent_notification` reveal pass   | Iterates the freshly-loaded `_agents` to find a PLAN/QUESTION row.                                                      |
| 4b  | `src/sase/ace/tui/actions/agents/_notification_modal_flow.py:48`        | Same handler, restore pass                  | Restores `hide_non_run_agents=True`.                                                                                    |
| 5a  | `src/sase/ace/tui/actions/agents/_notification_status_overrides.py:134` | External plan response (response file path) | Override already mutated. Returns True.                                                                                 |
| 5b  | `src/sase/ace/tui/actions/agents/_notification_status_overrides.py:145` | External plan response (marker file path)   | Same.                                                                                                                   |
| 5c  | `src/sase/ace/tui/actions/agents/_notification_status_overrides.py:155` | External plan response (request gone)       | Same.                                                                                                                   |
| 6   | `src/sase/ace/tui/actions/agents/_notification_question_modal.py:150`   | `_restore_pre_question_status`              | Restores override after question answered. Returns.                                                                     |
| 7a  | `src/sase/ace/tui/actions/agents/_revive.py:393`                        | `_do_revive_agent` (single)                 | Followed by `_refresh_agents_display(list_changed=True)` and `_select_revived_agent(agent)`. Needs `full_history=True`. |
| 7b  | `src/sase/ace/tui/actions/agents/_revive.py:539`                        | `_do_revive_agents` (batch)                 | Same: refresh display + select first revived candidate.                                                                 |
| 8   | `src/sase/ace/tui/actions/agents/_loading_filter.py:39`                 | `_refilter_agents` fallback                 | First-load fallback when `_agents_with_children` is empty.                                                              |

## Migration strategy by group

### Group A — pure refilter / display callers (sites 1, 2a, 2b, 8)

These callers don't read agent state immediately after `_load_agents()` returns. They are the simplest to migrate.

**Pattern:**

```python
self._refilter_agents()                  # paint cached list with new filter
self._schedule_agents_async_refresh()    # disk reconcile
```

For site 1 (`app.py`), `_refilter_agents` already falls back to `_load_agents()` when `_agents_with_children` is empty
(site 8). We will:

- **Site 1 & site 8** together: change the `_refilter_agents()` empty-cache fallback (site 8) to call
  `_schedule_agents_async_refresh()` instead of `_load_agents()`. Then the `app.py` cold-load arm collapses to the same
  code as the cached-data arm — `self._refilter_agents()` followed by `self._schedule_agents_async_refresh()`. The
  first-paint loading indicator continues to render via the existing `_agents_first_load_done`/loading-row mechanism
  that `on_mount` and `_run_agents_async_refresh` already drive.
- **Sites 2a / 2b**: replace the `_load_agents()` line with `self._refilter_agents()` followed by
  `self._schedule_agents_async_refresh()`. The query/filter mutation hits `_agents_with_children` finalize on the
  in-memory pass and the disk reconcile catches anything new on disk. (The in-memory pass uses the cached
  `_agents_with_children` and re-runs filtering, so it honors the new `hide_non_run_agents` / `_agent_search_query`
  immediately.)

### Group B — status-override surfacing (sites 3, 5a, 5b, 5c, 6)

All five of these mutate `_agent_status_overrides[identity]` (or pop it) and then call `_load_agents()` purely to make
the override visible on the row.

Status overrides are read inside finalize (`_apply_loaded_agents` → `_apply_loaded_agents_prepared` →
`finalize_agent_list`), so a `_refilter_agents()` call surfaces them on the cached `_agents_with_children` immediately.

**Pattern:**

```python
self._agent_status_overrides[agent.identity] = "PLAN APPROVED"
self._refilter_agents()
self._schedule_agents_async_refresh()
```

This gives the user instant visual feedback (Group B's primary user expectation) and lets the disk reconcile catch any
other state changes asynchronously.

For **site 3** (plan feedback) the in-flight notification-count refresh (`_refresh_notification_count`) and prompt-bar
unmount happen on the same UI tick and are unaffected by the order swap.

### Group C — notification jump with reveal/restore (sites 4a, 4b)

`_jump_to_agent_notification` currently does:

```python
self.hide_non_run_agents = False
self._load_agents()                   # site 4a
for i, a in enumerate(self._agents):
    if a.status in ("PLAN", "QUESTION"): ...; break
if agent is None:
    self.hide_non_run_agents = True
    self._load_agents()               # site 4b
```

It needs the post-reveal list available _synchronously_ to scan for a PLAN/QUESTION agent. We can satisfy that with the
in-memory refilter because `_agents_with_children` already contains the hidden rows; only the visible filter (`_agents`)
was changed by setting `hide_non_run_agents`.

**Replacement:**

```python
self.hide_non_run_agents = False
self._refilter_agents()
... # existing scan over self._agents
if agent is None:
    self.hide_non_run_agents = True
    self._refilter_agents()
self._schedule_agents_async_refresh()  # disk reconcile in the background
```

Edge case: if the cache has not been populated yet (`_agents_with_children` is empty), `_refilter_agents` would fall
back. After the Group A refactor, that fallback schedules the async load without populating `_agents` synchronously, and
the for-loop scan would find nothing. The risk window is narrow (the user must trigger the keybind before any agent load
has completed), and the safe behavior is "do nothing this tick"; the user can re-press once data arrives. We document
this in a code comment.

### Group D — revive (sites 7a, 7b)

These need `full_history=True` and the post-load selection step to fire after the load completes.

There are two viable approaches:

1. **Schedule with full_history + post-refresh callback.** Extend `_schedule_agents_async_refresh` to accept an
   `on_complete: Callable[[], None] | None = None` argument that `_run_agents_async_refresh` invokes after a successful
   apply. The revive paths supply a closure that runs `_refresh_agents_display(list_changed=True)` and
   `_select_revived_agent(agent)`.
2. **Inline async wrapper in revive.** Define the revive flow as a `worker` (Textual `run_worker`) that awaits a small
   async helper which performs the same merge → load → apply phases as `_load_agents_async` and then runs the selection
   logic.

**Recommendation: approach 1.** The completion-callback hook is useful beyond revive (it's the cleaner shape for site
3's notification refresh too if we ever want to pivot it), and it keeps the coalescing/last-request-wins semantics of
`_schedule_agents_async_refresh` intact. The callback contract:

- Fires on the same UI tick as the apply step (after `_apply_loaded_agents_prepared` returns inside
  `_load_agents_async`).
- Fires only for the run that consumed the request (if the run was coalesced into a pending follow-up, only the
  follow-up's callback fires).
- Multiple pending callbacks accumulate; we run them in FIFO order after the apply step.

Implementation sketch in `_loading_refresh.py`:

```python
def _schedule_agents_async_refresh(
    self,
    *,
    full_history: bool = False,
    on_complete: Callable[[], None] | None = None,
) -> None:
    if on_complete is not None:
        self._agents_refresh_pending_callbacks.append(on_complete)
    ...

async def _run_agents_async_refresh(self) -> None:
    ...
    callbacks = list(self._agents_refresh_pending_callbacks)
    self._agents_refresh_pending_callbacks.clear()
    try:
        await load_agents_async(...)
    finally:
        self._agents_loading = False
        for cb in callbacks:
            try:
                cb()
            except Exception:
                log.exception("agents async refresh callback failed")
        ...
```

State additions (in `_loading_state.py`):

```python
_agents_refresh_pending_callbacks: list[Callable[[], None]]
```

Initialized to `[]` in startup.

The revive sites become:

```python
def _on_revive_loaded() -> None:
    if self.current_tab == "agents":
        self._refresh_agents_display(list_changed=True)
        self._select_revived_agent(agent)

self._schedule_agents_async_refresh(
    full_history=True,
    on_complete=_on_revive_loaded,
)
```

The batch case captures `revive_candidates` in the closure and walks them looking for the first match. We also remove
the eager `_load_agents(full_history=True)` call at sites 7a/7b.

### Pre-mutation refilter for revive

To avoid the row visibly disappearing while the async load is in flight, the revive paths should also call
`_refilter_agents()` immediately after they mutate `_dismissed_agents` (which they already do today via the
dismissed-set discard before save), so the cached `_agents_with_children` re-derives without the dismissed identity.
This matches the "mutate local state, patch the visible row, then schedule the disk reconcile" guidance from the audit.

(If `_refilter_agents` doesn't already react to changes in `_dismissed_agents`, we will verify and either teach it to or
explicitly rebuild the relevant slice. Initial reading suggests it just re-runs finalize on the cached list, which
already filters by status overrides but may not reflect dismissed-set membership without re-running the merge. If so we
can either drop the pre-revive refilter and accept a brief "still showing dismissed" window, or trigger an in-memory
rebuild from the dismissed-set discard. The plan defers the exact mechanism to the implementation step pending a short
verification.)

## Test plan

We piggyback on the existing async-refresh test surface. Specifically:

1. **Unit tests** (new) in `tests/ace/tui/test_loading_callbacks.py`:
   - `_schedule_agents_async_refresh` accepts and runs an `on_complete` callback after `_load_agents_async` completes.
   - Multiple pending callbacks fire in FIFO order on a single run.
   - A coalesced follow-up run fires its own callbacks (registered during the in-flight run) but does not re-run the
     prior run's callbacks.
   - Exceptions in one callback do not block subsequent callbacks.
2. **Site-specific tests** (extend existing files where possible):
   - `tests/ace/tui/test_agents_refresh_coalescing.py` — add cases asserting `_toggle_hide_non_run_agents` and the
     query-edit dismiss path no longer call `_load_agents` synchronously (monkeypatch `_load_agents` to raise; assert
     `_refilter_agents` and `_schedule_agents_async_refresh` fired).
   - `tests/test_plan_rejection_response.py` — verify plan-feedback submit triggers the override + refilter + schedule,
     not a sync `_load_agents`.
   - New `tests/ace/tui/test_notification_jump_async.py` — verify `_jump_to_agent_notification` discovers the
     PLAN/QUESTION row from the cached `_agents_with_children` after toggling `hide_non_run_agents`, with `_load_agents`
     patched to raise.
   - New `tests/ace/tui/test_revive_async_refresh.py` — verify revive single + batch use the async refresh with
     `full_history=True` and the on-complete callback runs the selection step.
3. **Visual / integration**: existing `tests/ace/tui/test_post_launch_jk_lag.py` and
   `test_event_handlers_dirty_flags.py` should still pass without modification — they cover the same async-refresh
   contract we're extending. If any test patches `_load_agents` directly (via `monkeypatch`), those patches need to move
   to `_load_agents_async` or to the underlying loader.
4. **Manual smoke test** before merge:
   - Cold-launch ACE → switch to Agents tab → confirm loading row, then list paints, then pressing `j`/`k` is responsive
     immediately.
   - Toggle `H` (hide non-run) and confirm no perceptible stall.
   - Edit Agents query (`/`) with a plain word; confirm the modal closes and the list updates without a freeze.
   - Trigger plan feedback flow (reject with feedback); confirm the row flips to RUNNING immediately and the prompt bar
     unmounts.
   - Open the notification modal jump-to-agent path while `hide_non_run_agents` is True; confirm the matching row is
     selected without freezing.
   - Revive a dismissed agent; confirm the row reappears and is selected.

## Sequencing

1. Implement the `on_complete` callback hook in `_loading_refresh.py` and the `_agents_refresh_pending_callbacks` state
   field. Add unit tests.
2. Migrate Group A sites (filter actions, app.py first-tab, `_refilter_agents` fallback). Run targeted tests + lint.
3. Migrate Group B sites (status overrides, plan feedback, restore pre-question status).
4. Migrate Group C site (`_jump_to_agent_notification`).
5. Migrate Group D sites (revive single + batch) using the new callback hook. Verify revive selection works.
6. Run `just check` (lint + mypy + tests) and `just test-visual` to confirm no regressions.
7. Manual smoke pass.

## Open questions / verification points (to confirm in implementation)

- Confirm `_refilter_agents` reflects post-mutation `_dismissed_agents` (revive case). If not, decide between an
  in-memory rebuild helper or accepting a short "still showing dismissed" window before the async load completes.
- Confirm no test monkeypatches `_load_agents` in a way that breaks when callers stop invoking it. Migrate any such
  patches to `_load_agents_async` or to the disk-loader callable resolved by
  `_resolve_load_agents_from_disk_with_state()`.
- Confirm the cold-load path correctly displays the loading indicator after migration (Site 1 + Site 8 collapse). If the
  indicator only renders on a path that previously assumed a synchronous load completion, we may need to flip the
  `_agents_loading` flag before scheduling so the row paints.

## Out-of-scope follow-ups (mentioned for traceability)

- Move agent-query content search off-thread (audit High Severity #2).
- Decouple artifact discovery from detail rendering (#3).
- Cache workflow JSON (#4).
- Cache ChangeSpec RUNNING claims (#5).
- Run-log modal off-thread loading (#6).
