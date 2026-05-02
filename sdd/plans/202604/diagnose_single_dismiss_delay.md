---
create_time: 2026-04-24 21:43:10
status: done
prompt: sdd/prompts/202604/diagnose_single_dismiss_delay.md
---
# Diagnose & Fix the Lingering TUI Delay After Single-Agent Dismiss

## Problem

Pressing the dismiss key on a completed/dismissable agent in the **Agents** tab still feels laggy: the agent leaves the
list immediately, but the next keystroke (j/k, tab switch, ?) is noticeably delayed for a beat. This is despite four
prior responsiveness passes:

- `cbffc488` made single-agent dismissals async (worker-thread persistence).
- `60da6d9d` batched marked agent kills.
- `f710dd20` made launch/kill refresh paths responsive.
- `09a207d4` moved launch off the main thread.

The issue is real and reproducible — see `sase_plan_ace_agent_tab_responsiveness.md` for the long-standing multi-phase
plan that listed the candidate causes but only partially shipped.

## What we already know

The single dismiss path (`src/sase/ace/tui/actions/agents/_dismissing.py:272 _dismiss_done_agent`) is split into:

1. **Optimistic synchronous prologue (main thread).** Flips in-memory state, emits the toast, calls
   `_apply_dismissal_in_memory([agent])` which routes through `_refilter_agents()` → `_finalize_agent_list()` →
   `_refresh_agents_display(list_changed=True, defer_detail=True)`. The widget update is `AgentList.update_list`
   (`agent_list.py:153`), which **clears every option and re-renders every row through Rich** before adding it back.
2. **Worker-thread persistence.** `asyncio.to_thread(persist_single_dismiss_transaction, ...)` writes `dismissed.json`,
   deletes artifact dirs, releases the workspace, removes notifications, saves bundles.
3. **`finally` block (back on the asyncio event loop, i.e. main thread):**
   ```python
   self._refresh_notification_count()           # synchronous load of notifications.jsonl
   self._schedule_agents_async_refresh()         # triggers a full disk reload + main-thread rebuild
   ```

`_run_agents_async_refresh` then calls `_load_agents_async` which scans every `.gp` file (Phase 2 caching from the prior
plan was not landed), and finally runs `_apply_loaded_agents` → `_finalize_agent_list` → another **full `update_list`**
rebuild — for a list whose only delta vs. the prologue rebuild is "the same agent we already removed."

## Root-cause hypotheses (ranked)

### H1 — The post-persistence reload re-renders the entire agent list, blocking the main thread a few hundred ms after the dismiss

This is the most likely "still there" delay. The user feels it because the prologue rebuild lands fast enough to mask,
but the _second_ full rebuild lands right when they're trying their next keystroke.

- The dismiss worker only writes `dismissed.json`, deletes artifacts, removes notifications, releases workspace, saves
  the bundle. **None of those operations change the data the loader reads from `.gp` files**, so the post- persistence
  reload reads disk only to confirm the state we already have in memory.
- The reload is therefore **redundant** for the dismiss path. (Compare to kill: kills _do_ rewrite `.gp` files via
  `update_changespec_*_field`, so post-kill reload still has a reason to exist; even there, the same cache argument
  applies.)
- Cost is dominated by `find_all_changespecs()` parsing every `.gp` file (Phase 2 of the old plan never landed) plus a
  second `update_list` rebuild on the main thread.

### H2 — `_refresh_notification_count()` does synchronous disk I/O on the main thread inside the post-persistence finally

`src/sase/ace/tui/actions/agents/_notifications.py:223` calls `load_notifications()` which opens
`~/.sase/notifications/notifications.jsonl`, takes a shared `flock`, reads every line, JSON-parses each. This runs on
the main thread, immediately before the redundant reload. With a few hundred notifications the parse alone is tens of
ms; with the file lock contended (the worker thread also writes notifications) it can stall longer.

### H3 — The optimistic prologue itself rebuilds the entire `OptionList` instead of removing one row

`AgentList.update_list` does `clear_options()` followed by an `add_option(...)` per row, with a Rich
`_format_agent_option` per row plus `_format_attempt_option` per attempt. With 50–100 visible agents this is the 50–150
ms band Phase 3 of the prior plan called out. Phase 3 was specced but never implemented; the dismiss path still pays the
full cost on the prologue.

### H4 — `_apply_dismissal_in_memory` runs the entire `_finalize_agent_list` pipeline (fold filter, ordering, search filter, status overrides, panel index build, tab-bar count) when only one row needs removal

Compare with the kill path: `_apply_killed_agents_in_memory` (`_killing.py:96`) just filters `_agents` /
`_agents_with_children`, calls `_build_panel_indices`, and refreshes — it skips re-applying ordering/search/status
overrides because those were already applied to `_agents`. The dismiss path goes through `_refilter_agents` which copies
`_agents_with_children` back into `_agents` and re-runs everything. Each individual stage is cheap, but they add up to
~5–15 ms on top of H3.

### H5 — Coalescing: rapid successive dismisses queue multiple reloads

`_schedule_agents_async_refresh` already has last-request-wins coalescing, but each post-persistence finally
unconditionally calls it. Two dismisses in a second produce two reloads. The first finishes its widget rebuild while the
user is mid-keystroke for the third dismiss.

## Diagnostic step (cheap, one commit, do this first)

Before committing to a fix, **prove which hypothesis dominates** in the user's actual environment. The codebase already
has `log.debug` timing on the relevant functions — we just need to surface the numbers without changing behavior.

1. Run `sase ace` with `LOG_LEVEL=DEBUG` (or whatever the project's debug-log toggle is — verify in
   `src/sase/ace/tui/app.py` startup) for one session of "dismiss a single done agent."
2. Read off the existing log lines:
   - `agent dismiss persistence: identity=... elapsed=...` — worker-thread cost.
   - `agents display refresh list phase: elapsed=...` — main-thread `update_list` cost.
   - `agents async load: disk=... apply=...` — post-persistence reload cost.
3. Add **one** new timing line around `_refresh_notification_count` inside the dismiss `finally` so we can attribute the
   pause to H2 vs. H1 vs. the second `update_list` rebuild. This is the only instrumentation change.

The expected reading on a populated `~/.sase/projects/`:

| Stage                         | Hypothesis       | Expected                                  | Observed (to fill in) |
| ----------------------------- | ---------------- | ----------------------------------------- | --------------------- |
| Prologue `update_list`        | H3 + H4          | 50–150 ms                                 |                       |
| Worker persistence            | (already async)  | not user-blocking                         |                       |
| `_refresh_notification_count` | H2               | 5–80 ms                                   |                       |
| Reload disk I/O               | H1 (worker)      | 100–400 ms (not user-blocking)            |                       |
| Reload `apply`                | H1 (main thread) | 50–200 ms ← **likely the perceived hang** |                       |

If the second `apply` is the dominant blocker, **H1 is the root cause**. If the prologue rebuild is the dominant
blocker, H3 is. Both are likely contributors; we'll fix in order of measured impact.

## Fix strategy

The fix is sequenced so each step is independently shippable and observable. We stop after the perceived delay is gone,
even if not every step lands.

### Step 1 (likely sufficient by itself) — Drop the redundant post-dismiss reload

In `_run_dismiss_persistence_async`'s `finally`, replace `self._schedule_agents_async_refresh()` with a no-op (or guard
it with a flag so kills still trigger reload). The worker-thread persistence does not change any data the loader reads
from `.gp` files, so the optimistic in-memory state is already correct.

Risks:

- Another `sase` process modifying `.gp` files concurrently would normally be picked up by this reload. But the next
  periodic auto-refresh (`refresh_interval`) catches that within seconds — it does not need to fire on every dismiss.
  Document this in the docstring.
- A failed worker (caught by the existing `except`) currently still triggers the reload, which masks the failure by
  reverting in-memory state. Keep a reload **only on the failure branch**, where it doubles as recovery.

Move `_refresh_notification_count` off the main thread in the same step: swap the body to
`self.run_worker(self._refresh_notification_count_async, exclusive=False)` or wrap the disk read with
`asyncio.to_thread`. The widget update at the end stays on the main thread.

Expected impact: removes the second `update_list` rebuild and the synchronous notifications-file read from the critical
path. If the perceived delay is gone, **stop here**.

### Step 2 (only if Step 1 isn't enough) — Make the prologue widget update incremental

Implement Phase 3 of the prior plan, scoped to single-row removal:

- Add `AgentList.remove_row(global_idx)` and a corresponding hook on `_refresh_agents_display` that takes a
  `removed_identities: set[Identity] | None` kwarg.
- Have `_apply_dismissal_in_memory` call this fast path when exactly one agent (and possibly its workflow children) is
  removed and no fold/search/order state changed.
- Fall back to the full rebuild when the dismissed agent is a workflow parent whose removal would change a sibling's
  fold annotation — start conservative.

Expected impact: prologue rebuild drops from O(N × Rich render) to O(1 × Rich render). Roughly 50–150 ms saved on
populated lists.

### Step 3 (cleanup, low priority) — Have the dismiss path use the kill path's lighter in-memory remove

`_apply_dismissal_in_memory` should mirror `_apply_killed_agents_in_memory` instead of routing through
`_refilter_agents`. Skip the redundant fold/order/search/status pipeline; just filter `_agents` /
`_agents_with_children` directly, rebuild panel indices, refresh tab-bar counts, and refresh the display. Save 5–15 ms
and one source of duplicated logic.

## Out of scope

- **Phase 2 ChangeSpec mtime cache** — still worthwhile but no longer the bottleneck once Step 1 lands. Track
  separately.
- **Phase 4 worker-side `_finalize_agent_list` split** — only matters if Step 1 + Step 2 don't get us under the
  perceptible threshold, which is unlikely given the analysis.
- Bulk-kill responsiveness — `_run_bulk_kill_persistence_async` has the same redundant reload trigger, but the user
  reported the issue specifically for _single_ dismiss; bulk path can be addressed in a follow-up if Step 1's pattern
  generalizes (it should).

## Validation

1. **Manual:** populate `~/.sase/projects/` with 50+ agents, dismiss a completed one, verify the next j/k is responsive
   (no perceived hang). Compare the existing debug log lines before/after.
2. **Automated:** add a test that asserts `_run_dismiss_persistence_async`'s `finally` does **not** call
   `_schedule_agents_async_refresh` on success. Existing optimistic-dismissal tests in
   `tests/test_agent_dismiss_in_memory.py` cover the visible behavior.
3. **`just check`** must pass.

## Constraints

- Optimistic in-memory removal stays — this is the user-visible feedback signal.
- No runtime-specific branching.
- The startup-stopwatch fix from `95805755` and the `#tab-bar` guard from `73a0d57b` must continue to hold.
- Don't reintroduce blocking I/O on the main thread anywhere in the dismiss path.
