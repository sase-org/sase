---
create_time: 2026-05-10 12:28:27
status: done
---
# Plan: Notification panel — `M` for mute, `m` for mark, bulk dismiss with `x`

## Product context

The notification modal (the panel pushed by `?` / opened via the notifications shortcut) currently uses single-row
keymaps: `x` dismisses the highlighted row, `m` toggles mute, `s` snoozes. There is no way to dismiss several
notifications at once except by holding `x` repeatedly (which still requires a `y/n` confirmation per plan/question
row).

Other tabs in the TUI (notably the Agents tab — see `src/sase/ace/tui/actions/agents/_marking.py`) already establish a
"mark a row, then act on the marked set" pattern. We want the same affordance in the notification modal so the user can
sweep through a noisy inbox, mark the rows they want to clear, and dismiss them in one keystroke.

## Requested change

1. **Move mute** off the lowercase `m` slot and onto **uppercase `M`**. This is consistent with `R` (read all) and `V`
   (view image), which are also state-altering uppercase keys in this modal.
2. **Introduce `m` (mark)** to toggle a per-row mark.
3. **Overload `x`** so that, when at least one row is marked, it bulk-dismisses every marked row at once; otherwise it
   keeps its current single-row dismiss behavior.

Out of scope:

- A separate "clear marks" key. Marks are implicitly cleared when the modal closes; we'll also clear them after a bulk
  dismiss completes (no rows left to act on).
- Marks persisting across modal sessions. They live in modal state only.
- New mark-aware actions for mute/snooze. Bulk dismiss is the only mark-aware action in this iteration.

## High-level technical design

### State

Add modal-level state to `NotificationModal.__init__` (in `src/sase/ace/tui/modals/notification_modal.py`):

- `self._marked_notification_ids: set[str] = set()` — keyed by `Notification.id`, not by list index. Indices shift on
  dismiss; ids are stable.

### Bindings (`notification_modal.py`)

- Change `("m", "toggle_mute", "Toggle Mute")` → `("M", "toggle_mute", "Toggle Mute")`.
- Add `("m", "toggle_mark", "Mark")`.
- `x` → `action_dismiss_notification` already exists; we modify its handler (see below) to branch on marks.

### Mark action (new mixin method on `NotificationStateActionsMixin`)

`action_toggle_mark` lives next to the other state actions in `src/sase/ace/tui/modals/notification_modal_actions.py`.
Behavior:

1. Resolve the highlighted notification's id via `_get_highlighted_notification()`.
2. Toggle membership in `_marked_notification_ids`.
3. Auto-advance the cursor to the next visible row (mirroring `_advance_mark_selection` from `agents/_marking.py`, but
   reusing the existing `_visual_notification_index_order()` helper from `notification_modal_options.py`). Wraparound
   semantics match the agents tab.
4. Rebuild the option list so the row's marker glyph repaints. (We use `_rebuild_list` rather than a row-level patch
   because the existing modal already rebuilds for mute/snooze toggles — adding a row-level patch path is out of scope
   and would diverge from current behavior.)
5. Emit a small `notify(...)` confirmation only when there's a non-trivial state change worth surfacing — opting for
   silence on a single mark toggle to avoid toast spam, mirroring the agents tab.

### Marker glyph in the row label

In `notification_modal_options.py`, `_create_styled_label` is the only place that renders row chrome. Today the prefix
is one of `"~ "` (muted), `"* "` (unread), or `"  "` (read).

We will:

- Pass an `is_marked: bool` parameter into `_create_styled_label`. The current callers already either route through
  `_create_sectioned_options` (loop) or are tests calling with a single notification.
- When `is_marked`, prepend a high-contrast marker (e.g. `"▶ "` styled bold yellow) **before** the existing prefix, so
  the marker is visually distinct and doesn't interfere with read/mute state encoding. Final shape:
  `"▶ * [sender] note ..."`.
- `_create_sectioned_options` must look up `notification.id in self._marked_notification_ids` for each row and pass the
  flag in.

### `x` bulk-vs-single dispatch

In `action_dismiss_notification` (in `notification_modal_actions.py`):

- If `self._marked_notification_ids` is non-empty:
  - Compute `marked_indices = [i for i, n in enumerate(self._notifications) if n.id in self._marked_notification_ids]`.
  - If any marked notification has `action in ("PlanApproval", "UserQuestion")`, use the existing pending-confirm flow
    but at bulk granularity. We'll repurpose `_pending_confirm_notification_id` into a new
    `_pending_confirm_notification_ids: list[str] | None` attribute (id-based to survive index shifts).
    `action_confirm_dismiss_notification` and `action_cancel_dismiss_notification` are updated to handle either the
    legacy single-id field or the new bulk-id field; we keep both for backward compatibility with the existing
    single-row confirm path.
  - On confirm (or immediately, if no plan/question rows were marked): persist via the existing `mark_many_dismissed`
    (already used by `_bulk_dismiss_notifications_by_index`), drop the rows from `_notifications`, clear
    `_marked_notification_ids`, choose a sensible new highlight (the row immediately after the last dismissed visual
    position, or the previous row if we deleted the tail), and call `_rebuild_list`.
- If no rows are marked: behavior is unchanged (single-row dismiss with the existing per-row plan/question prompt).

### Helpers we can reuse

- `_mark_many_dismissed` (already wired to `mark_many_dismissed`) — no new persistence call needed.
- `_replacement_notification_id_after_dismiss` extends naturally: for bulk we want the replacement _after_ the last
  marked visual position; we'll add a small helper `_replacement_notification_id_after_bulk_dismiss(indices)` in
  `notification_modal.py` next to its single-row sibling.
- `_visual_notification_index_order()` already returns indices in display order, used both for the single-row
  replacement choice and for the new mark cursor advance.

### Hint text

Update `DEFAULT_HINT_TEXT` in `notification_modal_constants.py` so `m: mark` and `M: mute` are both surfaced. Final
shape (subject to width tweaks):

```
Enter: select  m: mark  x: dismiss  M: mute  s: snooze  e: edit  V: image  C-n/C-p: next/prev file  C-d/C-u: scroll  R: read all  q: close
```

Per `src/sase/ace/AGENTS.md` ("Help Popup Maintenance"), if there's a `?` help modal that documents this panel, we'll
update it too. Initial grep shows no notification-specific entries in the help modal — the modal's footer hint is the
documentation surface. We will recheck while implementing and update if anything turns up.

### Tests

Add to `tests/test_notification_modal_actions.py`:

1. `test_notification_modal_binds_capital_m_to_toggle_mute` and an explicit assertion that lowercase `m` is **not**
   bound to mute.
2. `test_toggle_mark_adds_id_to_marked_set` — asserts the highlighted id is added and the cursor auto-advances.
3. `test_toggle_mark_removes_id_when_already_marked` — toggle off path.
4. `test_marked_row_label_has_marker_prefix` — exercises the styled-label marker rendering.
5. `test_x_with_marks_bulk_dismisses_all_marked` — calls `action_dismiss_notification` with marks present and asserts
   `mark_many_dismissed` is called with the marked id set, the rows are removed, marks are cleared, and `_rebuild_list`
   is called once.
6. `test_x_with_marks_including_plan_question_requires_confirmation` — pending-confirm flow at bulk granularity; asserts
   no persistence happens until `action_confirm_dismiss_notification` runs.
7. `test_x_without_marks_unchanged_behavior` — guard that the no-marks path still dismisses only the highlighted row.

Also adjust the existing mute tests to reflect the binding move (action method signature is unchanged, so most tests
keep working — we only need to update the binding-introspection test).

### Risk and rollback

- The change is contained to four files (`notification_modal.py`, `notification_modal_actions.py`,
  `notification_modal_options.py`, `notification_modal_constants.py`) plus tests. No external CLI surface is affected.
- Users who muscle-memory `m` for mute will discover the new mute key via the footer hint and the help modal. We'll keep
  `M` discoverable in the hint text from day one.
- The bulk-dismiss persistence path already exists and is exercised by
  `test_bulk_dismiss_persists_once_removes_rows_and_rebuilds_once`, so the new code reuses a tested store call.

## Files touched

- `src/sase/ace/tui/modals/notification_modal.py` — bindings, marked-id state, replacement-after-bulk helper.
- `src/sase/ace/tui/modals/notification_modal_actions.py` — `action_toggle_mark`, bulk-aware dismiss/confirm/cancel.
- `src/sase/ace/tui/modals/notification_modal_options.py` — marker glyph in `_create_styled_label`, marked-id lookup in
  `_create_sectioned_options`.
- `src/sase/ace/tui/modals/notification_modal_constants.py` — `DEFAULT_HINT_TEXT`.
- `tests/test_notification_modal_actions.py` — new tests (above) and updated binding assertions.

## Validation

Run `just check` (lint + tests) from the workspace before reporting back.
