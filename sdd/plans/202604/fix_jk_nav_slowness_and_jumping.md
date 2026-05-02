---
create_time: 2026-04-27 10:40:04
status: wip
prompt: sdd/prompts/202604/fix_jk_nav_slowness_and_jumping.md
---
# Fix slow / jumping `j`/`k` navigation on the CLs tab

## Symptom

On the ACE TUI CLs tab, `j`/`k` navigation is very slow, and the cursor sometimes "snaps back" between the previously
selected ChangeSpec entry and the one the user was navigating to (visible as a quick jump back-and-forth).

## Background — the j/k path

```
key 'j' / 'k'
  → action_next_changespec / action_prev_changespec     (navigation/_basic.py)
    → self.current_idx += 1 / -= 1
      → watch_current_idx (app.py:262)
        → _refresh_changespecs_display_debounced (changespec.py:481)
          ├── list_widget.highlighted = self.current_idx     ← cheap, inline
          ├── _update_info_panel()                            ← cheap, inline
          └── _changespec_detail_debouncer.schedule(_refresh_display)
                                                              ← deferred 150ms

after 150ms quiescence, _refresh_display runs:
  → list_widget.update_list(self.changespecs, self.current_idx, ...)   ← EXPENSIVE
  → detail_widget.update_display(...)
  → ancestors_panel.update_relationships(...)
  → footer rebuild
```

`update_list()` (in `widgets/changespec_list.py:261`):

```python
self._programmatic_update = True
self.clear_options()
for i, cs in enumerate(changespecs):
    stats = _compute_mentor_stats(cs)         # ← FILE I/O per CL
    option = self._format_changespec_option(...)
    self.add_option(option)
    width = _calculate_entry_display_width(...)
    max_width = max(max_width, width)
self.post_message(self.WidthChanged(...))
self.highlighted = current_idx
self.call_later(self._clear_programmatic_flag)  # ← async clear
```

`_compute_mentor_stats` (changespec_list.py:46) calls — uncached — for every ChangeSpec on every rebuild:

- `_load_all_mentor_outputs(cl_name)` — globs `~/.sase/mentors/<cl>-*.json`, opens and JSON-parses each output file
- `load_acceptance_state(cl_name, entry_id)` — JSON file read
- `load_read_state(cl_name, entry_id)` — JSON file read

None of these are cached (`mentor_output.py:182,305,338` — no decorators, raw `Path.read_text` each time).

## Root causes

### 1. The "slowness": the entire CL list is rebuilt on every j/k pause, and the rebuild does sync file I/O for every CL.

Every time the user pauses j/k for >150ms, `_refresh_display()` calls `list_widget.update_list(...)`, which:

- clears all options,
- iterates **every** ChangeSpec and runs `_compute_mentor_stats`, which hits disk 3+ times per CL (mentor outputs glob,
  acceptance state, read state),
- re-adds each option to the OptionList,
- rebuilds option text + width measurements.

For a project with N change-specs and M mentor-output files per CL, this is O(N·M) sync reads on the Textual main thread
on every j/k pause. With ~30 CLs and a few mentor runs each, this can easily blow past the frame budget (30– hundreds of
ms).

The cheap inline path (`list_widget.highlighted = self.current_idx`) does already update the visible cursor immediately
— but pressing `j` again during the I/O-bound rebuild blocks the keypress from being processed until the rebuild
completes, so the user perceives "j is unresponsive."

This was introduced when "mentor comment stats" were added to the list entries
(`db48dc68 feat: Add mentor comment stats to CLs tab list entries`). Today's
`59bdafdc perf(ace): cache merged-config and mentor profiles` cached the _config and profile metadata_ but **not** the
per-CL mentor outputs / acceptance state / read state — those are still uncached.

### 2. The "jumping back-and-forth": stale `OptionHighlighted` echoes from the rebuild reset `current_idx` after the user has already moved past it.

`update_list()` synchronously assigns `self.highlighted = current_idx` and only _then_ schedules
`_clear_programmatic_flag` via `call_later`. The `OptionHighlighted` messages emitted by Textual's OptionList during the
rebuild (from `clear_options()`, from each `add_option`, from the `highlighted = X` setter) are posted to the message
queue — they are not delivered until later event-loop ticks.

There is no guarantee that **all** of those queued `OptionHighlighted` messages are dequeued before
`_clear_programmatic_flag` runs. In particular: when the rebuild itself takes longer than a frame, queued user `j`
keypresses can race ahead of the queued `OptionHighlighted` echoes. The realistic interleaving:

1. User on idx 5, presses `j`. `current_idx = 6`. Cheap path sets `list_widget.highlighted = 6`.
2. 150ms passes; debounce fires `_refresh_display()`.
3. `update_list(current_idx=6)` runs. `_programmatic_update = True`. The slow loop blocks the main thread for, say, 200
   ms while doing mentor-stats I/O. During this loop, OptionList queues several `OptionHighlighted` messages (including
   `option_index=6` from `self.highlighted = 6`).
4. `update_list` returns. `call_later(_clear_programmatic_flag)` is scheduled.
5. The user, frustrated by the pause, has pressed `j` again during step 3. That keypress is dequeued: `current_idx = 7`.
   Cheap path sets `highlighted = 7`, which queues a fresh `OptionHighlighted(7)`.
6. The event loop then drains queued messages. `_clear_programmatic_flag` may run **before** all the
   `OptionHighlighted(6)` echoes from step 3 are delivered, depending on `call_later` ordering vs message-queue
   ordering.
7. A stale `OptionHighlighted(option_index=6)` is delivered with `_programmatic_update = False`. It posts
   `SelectionChanged(6)`.
8. `on_change_spec_list_selection_changed` sets `current_idx = 6`.
9. `watch_current_idx` fires → cheap path sets `list_widget.highlighted = 6`.
10. User sees the cursor pop back from 7 to 6, then (when they press `j` again or the next debounce fires) pop forward
    again. That is the "back-and-forth flicker."

The boolean `_programmatic_update` flag with async clearing (changespec_list.py:280–326) is fundamentally racy: there is
no synchronization between the OptionList's internal `OptionHighlighted` post timing and `call_later`'s scheduling.

### 3. Compounding factor: the rebuild blocks pending user keystrokes.

Because the rebuild is sync I/O on the main thread, any j/k presses queued during the rebuild are starved until it
completes — making each "tap" feel like a lurch and giving the OptionList more time to spam stale echoes after the
rebuild ends.

## Diagnostic confidence

I'm confident in (1) — it's a direct read of the code, and the recent
`perf(ace): cache merged-config and mentor profiles` commit is exactly the shape of fix you'd expect if mentor-related
I/O on the list path was already suspected. I'm reasonably confident in (2) — it explains the "back-and-forth" symptom
precisely (the wrong index shows, then the right one comes back), and the racy flag pattern is an obvious smell. (3) is
mechanical given (1).

The plan should still include a quick verification step (instrument `update_list` and
`on_option_list_option_highlighted` with timing+counter logs, reproduce the symptom, confirm the dual smoking gun)
before settling on fixes.

## Fix plan

Three layered changes. Each is independently valuable; together they should restore instant, jitter-free j/k.

### Fix A — Don't rebuild the CL list on j/k navigation (eliminates symptoms 1 and 2 at the source)

The CL list contents do not change when the cursor moves. The current code nonetheless rebuilds the entire OptionList on
every debounced j/k refresh because `_refresh_display` is shared between j/k navigation and content-changing flows
(mark/unmark, hide-toggle, query-edit, auto-refresh, artifact-watcher).

Split the j/k path off:

- Introduce `_refresh_changespec_detail_only()` (or rename `_refresh_display` to `_refresh_full` and add a thin
  `_refresh_detail_only` variant). The new path skips `list_widget.update_list(...)` and only updates:
  - `detail_widget.update_display(...)` (or the hint-mode variant)
  - `ancestors_panel.update_relationships(...)`
  - `footer_widget.update_keybindings(...)` (whatever it is — same as today)
  - The inline `list_widget.highlighted = self.current_idx` already happens in `_refresh_changespecs_display_debounced`
    (changespec.py:503), so the cursor stays in sync without rebuilding options.
- Wire `_refresh_changespecs_display_debounced` (the j/k-driven entry point) to schedule the detail-only path instead of
  the full `_refresh_display`.
- Keep the full `_refresh_display` for non-navigation callers (`_reload_and_reposition_async`, mark/unmark, query/filter
  changes, hint mode, auto-refresh, artifact change, etc.) — the places where list contents actually change.

This eliminates the per-j/k mentor-stats I/O, restores instant cursor movement, and removes the source of stale
`OptionHighlighted` echoes (because no `clear_options` / `add_option` / `highlighted = …` storm runs on j/k).

### Fix B — Cache mentor stats so the list rebuild itself is cheap when it does run

Even after A, the full rebuild path still runs on auto-refresh (every `refresh_interval` seconds) and on
artifact-change. Today that path also does N×3 file reads, which contributes to perceived latency at refresh time.

Two reasonable shapes — pick during implementation:

1. **Function-level mtime cache** in `mentor_output.py`: memoize `_load_all_mentor_outputs`, `load_acceptance_state`,
   `load_read_state` keyed on `(args, file_mtime)` (or directory mtime for the glob case). Invalidate on mtime change.
   Small dict; bounded by number of CLs.
2. **App-level cache in `_compute_mentor_stats`**: memoize the result of `_compute_mentor_stats(cs)` keyed on
   `(cl_name, entry_id, mtime_signature)` on the `ChangeSpecList` instance, invalidated when the artifact watcher fires
   `_on_artifact_change`. This is more localized and avoids polluting the storage layer.

The mtime check is required for correctness — the artifact watcher exists specifically because mentors and
acceptance/read state can change out of band. With mtime keying, cache invalidation is automatic; an explicit "clear"
hook on artifact change is a nice-to-have safety belt.

### Fix C — Make programmatic-update detection deterministic (defense in depth)

Replace the boolean `_programmatic_update` flag + `call_later` clear with an explicit "expected echoes" mechanism. Track
the most recent index we programmatically assigned to `self.highlighted`; in `on_option_list_option_highlighted`, drop
events whose `option_index` matches that tracker (consume the tracker on the first match). Roughly:

```python
def update_list(self, ...):
    ...
    self._programmatic_highlight_idx = current_idx
    self.highlighted = current_idx
    # no call_later flag clear

def on_option_list_option_highlighted(self, event):
    if (
        event.option_index is not None
        and event.option_index == self._programmatic_highlight_idx
    ):
        self._programmatic_highlight_idx = None
        return
    if event.option_index is not None:
        self.post_message(self.SelectionChanged(event.option_index))
```

Real user-driven cursor changes (e.g. arrow-key navigation that hits OptionList's own `cursor_up`/`cursor_down`
bindings, mouse interaction) still flow through. Programmatic echoes from `update_list` are reliably squashed.

This change is also worth keeping after Fix A, because non-j/k callers still go through the full rebuild and still emit
programmatic echoes.

### Fix order and verification

1. Add a temporary log (or pytest-style print) to `update_list` and `on_option_list_option_highlighted` recording
   wall-clock duration and event indexes. Reproduce the slowness and the back-and-forth on a project with several CLs
   and at least one with mentor outputs. Confirm the diagnosis (long `update_list` durations during j/k bursts, stale
   highlighted events arriving with `event.option_index != current_idx`).
2. Implement Fix A. Re-run the repro: j/k should now feel instant; rebuilds only happen on actual content changes.
   Confirm no regression in the mark, hint, hide-toggle, auto-refresh, and artifact-watcher flows (these still need to
   rebuild — they call `_refresh_display`, not the new detail-only path).
3. Implement Fix C. Re-run with the temporary log; the stale-echo path should now no-op deterministically. Remove the
   log.
4. Implement Fix B. Validate that auto-refresh-driven rebuilds are also cheap. Make sure cache invalidates when the
   artifact watcher fires (write a new mentor output, observe stat update on the next refresh).
5. Run `just check` from the workspace.

## Out of scope

- General TUI redesign of the CL list widget (e.g. moving to a virtual list or DataTable). The current OptionList shape
  is fine once the rebuild storm is gone.
- Auto-refresh interval changes — the `NavigationGate` already defers auto-refresh during j/k bursts; that's working as
  designed.
- Mentor-stats display format changes.

## Files likely to change

- `src/sase/ace/tui/actions/changespec.py` (Fix A: split detail-only refresh)
- `src/sase/ace/tui/widgets/changespec_list.py` (Fix C: programmatic-echo tracking; possibly Fix B: instance-level stats
  cache)
- `src/sase/ace/mentor_output.py` (Fix B option 1: function-level mtime caches on `_load_all_mentor_outputs`,
  `load_acceptance_state`, `load_read_state`)
- `src/sase/ace/tui/actions/event_handlers.py` (Fix B: hook `_on_artifact_change` to clear stats cache, if going with
  the app-level cache form)

No changes to keybindings, NavigationGate, or DetailPanelDebouncer.
