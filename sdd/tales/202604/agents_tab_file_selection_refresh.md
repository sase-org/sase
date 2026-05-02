---
create_time: 2026-04-22 16:57:35
status: done
prompt: sdd/prompts/202604/agents_tab_file_selection_refresh.md
---

# Plan: Preserve agent file-panel selection across auto-refresh

## Problem

On the Agents tab of the `sase ace` TUI, pressing `<ctrl+n>` (or `<ctrl+p>`) advances the highlighted file in the file
panel. On the next auto-refresh tick, that selection silently resets to the first file. Same symptom for both active
agents (with live diff + extra static files) and completed agents (with a static `all_files` list).

The auto-refresh should be a no-op with respect to user-driven UI state. Today it isn't.

## Root cause

The file panel rebuilds its file list and resets `_current_file_index = 0` on refresh in two distinct code paths:

### Path A — active agents, `update_display()` no-cache branch

`src/sase/ace/tui/widgets/file_panel/__init__.py` lines 53–151.

`AgentDetail.update_display()` → `AgentFilePanel.update_display(agent, stale_threshold_seconds=...)` fires on every
auto-refresh for the selected agent. Inside `AgentFilePanel.update_display()` there are four branches:

1. `same_agent && fresh cache` (lines 68–73): early-return. ✓ preserves index.
2. `same_agent && stale cache` (lines 74–82): starts background fetch + early-return. ✓ preserves index.
3. `same_agent && in-flight worker && no cache` (lines 84–93): early-return. ✓ preserves index.
4. `else` (lines 95–98): **full reset** — `self._current_file_index = 0`. ✗

Branch (4) is reached not only when the agent identity genuinely changes, but also when `same_agent=True` and
`cache_entry is None` and no worker is currently running. That state is reachable when:

- the prior fetch errored (`WorkerState.ERROR` never writes the cache entry), or
- a refresh tick fires before the first worker has populated the cache (timing-dependent, rare but possible).

Hitting branch (4) with `same_agent=True` clobbers `_current_file_index` to 0 and also rebuilds `_file_list` from
scratch at lines 100–116.

### Path B — completed agents, `set_file_list()` no-op check is too strict

`src/sase/ace/tui/widgets/file_panel/__init__.py` lines 153–182, called from
`src/sase/ace/tui/widgets/agent_detail.py:143`:

```python
# DONE, FAILED, etc.
files = agent.all_files
if files:
    file_panel.set_file_list(files, start_index=0)
```

The caller always passes `start_index=0` as a defensive default. Inside `set_file_list`:

```python
if files == self._file_list and start_index == self._current_file_index:
    return
self._reset_trim_state()
self._file_list = list(files)
self._current_file_index = min(start_index, len(files) - 1) if files else 0
```

When the user has pressed `<ctrl+n>` so `_current_file_index == 1`, the conjunction fails (`0 != 1`) and execution falls
through to the reset block even though `files` is unchanged. Result: `_current_file_index` resets to 0 on every refresh.

Additionally, `set_file_list()` unconditionally clears `self._current_agent = None` at line 168. That is why `Path A`'s
`same_agent` check cannot rescue DONE agents — by the time a subsequent refresh reaches `update_display()`,
`_current_agent` has already been nulled.

### Why the existing same-agent guards don't save us

The intent of the three early-return branches in `update_display()` and the no-op check in `set_file_list()` is clearly
to preserve user state on refresh. They just don't cover every path. The cleanest fix is to treat "current file
identity" as first-class state that survives any refresh of the same underlying agent.

## Fix

Two focused, local changes in `file_panel/__init__.py`. No new abstractions, no signature changes to callers.

### Change 1 — `update_display()`: preserve selected file by path match on same-agent rebuild

Before the "full reset" block (current line 95), snapshot the currently-displayed path when `same_agent=True`:

```python
saved_path: str | None = None
if same_agent and self._file_list and 0 <= self._current_file_index < len(self._file_list):
    saved_path = self._file_list[self._current_file_index]
```

After `self._file_list` is rebuilt at lines 100–116, restore the index by path match if possible:

```python
if saved_path is not None and saved_path in self._file_list:
    self._current_file_index = self._file_list.index(saved_path)
    self.post_message(
        FileListChanged(
            file_count=len(self._file_list),
            file_index=self._current_file_index,
        )
    )
```

The `post_message` above replaces the existing `FileListChanged` at lines 109–114 when we successfully restore —
otherwise keep the original message. If `saved_path` isn't in the rebuilt list (e.g., the agent's `extra_files`
changed), the index already defaults to 0 from line 97 and the original message path runs. The existing
`_display_file_at_current_index()` call on line 124 then renders whichever file we landed on.

Scope: only fires when `same_agent=True`. Cross-agent switches keep the current reset-to-0 behavior.

### Change 2 — `set_file_list()`: no-op on unchanged file list regardless of `start_index`

Replace:

```python
if files == self._file_list and start_index == self._current_file_index:
    return
```

with:

```python
if files == self._file_list and self._file_list:
    # Files unchanged — preserve the user's current_file_index regardless
    # of the caller's default start_index. Auto-refresh must not overwrite
    # a user selection driven by <ctrl+n>/<ctrl+p>.
    return
```

Rationale: the only caller, `AgentDetail.update_display()`, always passes `start_index=0`. `start_index` is a
first-assignment default, not a per-refresh user intent. If a future caller needs to force a particular index on an
unchanged list, they can either use `next_file()`/`prev_file()` or add a dedicated method — YAGNI until then.

### Change 3 (defensive) — `set_file_list()`: preserve selection when the file list _does_ change

When `files != self._file_list` but the currently-displayed file is still in the new list, preserve it. Otherwise fall
back to `start_index` (existing behavior). Replace the reset block at lines 172–174 with:

```python
old_path: str | None = None
if self._file_list and 0 <= self._current_file_index < len(self._file_list):
    old_path = self._file_list[self._current_file_index]

self._reset_trim_state()
self._file_list = list(files)
if old_path is not None and old_path in self._file_list:
    self._current_file_index = self._file_list.index(old_path)
else:
    self._current_file_index = min(start_index, len(files) - 1) if files else 0
```

This covers the rare case where `agent.all_files` grows between refreshes (e.g., a post-completion artifact appears)
without discarding the user's selection.

### Intentionally NOT changing

- `self._current_agent = None` at line 168 in `set_file_list()` — preserving that defensive clear keeps the
  cross-agent-switch invariant that the file panel can always detect a genuine agent change. The two changes above make
  this assignment irrelevant for the bug: user state is now preserved via file-path identity, not agent identity.
- `_pick_up_extra_files()` — runs only when `self._file_list` is empty, so there's no selection to preserve.
- `on_worker_state_changed()` sentinel-insert path (lines 363–381) — already preserves the user's file by bumping
  `_current_file_index` when inserting the sentinel. Correct as-is.
- `AgentDetail.update_display()` in `agent_detail.py` — no caller-side change needed; the fix lives in the widget that
  owns the state.

## Phases

### Phase 1 — Implement the widget fix

**File:** `src/sase/ace/tui/widgets/file_panel/__init__.py`

Apply Changes 1, 2, and 3 as described above. All three changes are local to this single file. No new helpers, no new
public methods.

### Phase 2 — Unit tests

**File:** `tests/ace/tui/test_file_panel_selection_preserved.py` (new)

New tests that directly exercise `AgentFilePanel` state transitions. Use the existing test fixtures for `Agent` objects
(look at `tests/ace/tui/test_file_panel*.py` neighbors for pattern; see `tests/ace/tui/conftest.py` for widget-mounting
helpers).

Tests to add:

1. **`test_ctrl_n_index_survives_no_cache_refresh`** — mount an `AgentFilePanel`; call `update_display(agent)` with an
   active agent that has two `extra_files`; simulate `next_file()` so `_current_file_index = 1`; clear the file cache
   entry; call `update_display(agent)` again with the same agent; assert `_current_file_index == 1` and `_file_list[1]`
   still points to the second extra file.

2. **`test_ctrl_n_index_survives_set_file_list_refresh`** — mount panel; call `set_file_list([a, b], 0)`; simulate
   `next_file()` so `_current_file_index = 1`; call `set_file_list([a, b], 0)` again; assert `_current_file_index == 1`.

3. **`test_set_file_list_preserves_selection_when_list_grows`** — call `set_file_list([a, b], 0)`; `next_file()` → index
   1 pointing at `b`; call `set_file_list([a, b, c], 0)`; assert `_current_file_index == 1` (still on `b`).

4. **`test_set_file_list_falls_back_to_start_index_when_old_file_missing`** — call `set_file_list([a, b], 0)`;
   `next_file()` → index 1 on `b`; call `set_file_list([a, c], 0)`; `b` is gone, so `_current_file_index` should fall
   back to `start_index=0`.

5. **`test_update_display_cross_agent_switch_still_resets`** — call `update_display(agent_x)`; `next_file()` → index 1;
   call `update_display(agent_y)` (different identity); assert `_current_file_index == 0` (cross-agent reset preserved).

6. **`test_update_display_same_agent_restores_sentinel_when_index_was_on_sentinel`** — seed cache entry with a diff so
   the rebuilt list contains `_LIVE_DIFF_SENTINEL` at position 0; user is on sentinel (index 0); simulated no-cache
   refresh should keep them on the sentinel after rebuild.

Each test should manipulate `file_cache` directly (it's a module-level dict imported from `_messages`) to force the
target branch without running real background workers. Follow the mocking pattern already in use in
`tests/ace/tui/test_file_panel_*.py` to stub out `run_worker` and `_fetch_file_in_background`.

### Phase 3 — Manual verification

Run `just check` (install + lint + mypy + pytest). Then smoke-test the TUI:

1. `sase ace` in a project with at least one active agent whose extra_files has ≥ 2 entries (e.g., plan + diff).
2. Select the agent; wait for the file panel to populate; press `<ctrl+n>` to move off index 0.
3. Wait at least `refresh_interval` seconds for an auto-refresh tick.
4. Confirm the file panel still shows the file selected in step 2 (no reset).
5. Repeat with a DONE agent (`all_files` static list): `<ctrl+n>` then wait for refresh — selection should persist.
6. Verify cross-agent navigation (`j`/`k`) still resets the file-panel index to 0 (or to the plan-default per
   `_pick_up_extra_files`) — we don't want to over-preserve and break agent-switch UX.

## Risks / open questions

1. **Sentinel semantics.** `_LIVE_DIFF_SENTINEL = "__live_diff__"` is treated like a real path in `_file_list`. Because
   the sentinel value is stable across rebuilds, Change 1's `saved_path in self._file_list` lookup works for it too — if
   the rebuilt list happens to include the sentinel, the user stays on the live diff. If the rebuilt list no longer has
   it (no diff cached yet), we fall back to index 0, which lands on the first extra file. Acceptable.
2. **Duplicate paths in `extra_files`.** `list.index()` returns the first occurrence. If an agent somehow lists the same
   path twice and the user was on the second occurrence, we'd land on the first after refresh. Vanishingly rare and not
   meaningfully worse than today's reset-to-0. Not worth guarding.
3. **`FileListChanged` message emission.** After Change 1, we need to keep exactly one `FileListChanged` post per
   `update_display()` call — emit it with the restored index when the same-agent restore fires, otherwise keep the
   existing emission on line 109. Test coverage in Phase 2 will catch a double-post if it slips in.
4. **Interaction with the worker-completion branch in `on_worker_state_changed` (line 373–381).** That branch inserts
   the sentinel at position 0 and bumps `_current_file_index += 1` when the diff first arrives. Our changes don't touch
   that code. After our fix, the sequence "first worker completes → sentinel inserted, index bumped → user presses
   `<ctrl+n>` → refresh fires" still works: the cache is now populated, so `update_display()` takes branch (1) or (2)
   and early-returns before hitting our new logic.
5. **No change to behavior on agent-switch.** `same_agent=False` still resets. Verified by test
   `test_update_display_cross_agent_switch_still_resets`.
