---
status: draft
create_time: 2026-04-30 18:55:08
prompt: sdd/prompts/202604/notification_recent_first.md
---

# Notification Panel Recent-First Bucket Ordering

## Problem

The notification modal groups unread notifications into fixed status buckets:

- `PRIORITY`
- `INBOX`
- `MUTED`

Inside each bucket, the modal currently preserves the order of `self._notifications`. That list comes from
`load_notifications()`, which reads the JSONL notification store in file order. New notifications are appended to the
store, so the current visual result is effectively oldest-first within each bucket. In practice, the most recently
triggered notification lands at the bottom of its bucket, which is the opposite of the scan pattern users expect for an
inbox-style panel.

The desired behavior is: keep the existing bucket taxonomy and bucket order, but sort each bucket so the newest
notification appears first.

## Goals

1. Preserve the existing bucket order: `PRIORITY` -> `INBOX` -> `MUTED`.
2. Sort notifications within each bucket by `Notification.timestamp`, newest first.
3. Keep all existing row actions working by continuing to use the original `self._notifications` index as each option
   id.
4. Keep display-only ordering local to the modal; do not rewrite or reorder the JSONL notification store.
5. Add focused tests that would fail under the current oldest-first behavior.

## Non-Goals

- No notification schema changes.
- No storage-level sorting in `load_notifications()`.
- No changes to priority classification, mute/snooze semantics, toast ordering, or the top-bar indicator.
- No changes to bucket labels or section styling.

## Current Code Path

The relevant files are:

- `src/sase/ace/tui/actions/agents/_notifications.py`
  - `_show_notification_modal()` loads notifications with `load_notifications()`, filters unread non-silent rows, and
    passes them directly into `NotificationModal`.
- `src/sase/ace/tui/modals/notification_modal.py`
  - Owns selection, rebuilds, dismissal replacement, and modal lifecycle.
- `src/sase/ace/tui/modals/notification_modal_options.py`
  - `NotificationOptionMixin._create_sectioned_options()` groups notifications by section and emits header/options in
    visual order.
  - `_visual_notification_index_order()` derives keyboard/dismiss/jump visual order from `_create_sectioned_options()`.
- `src/sase/notifications/store.py`
  - `append_notification()` appends JSONL rows.
  - `load_notifications()` returns parsed rows in file order.

The narrow behavioral point is `_create_sectioned_options()`: it builds `groups[key]` by iterating
`enumerate(self._notifications)` and then renders each `groups[key]` list unchanged. That is where display order should
change.

## Design

Add a small timestamp sort helper in `notification_modal_options.py` and apply it per bucket before rendering options.

The helper should:

- Parse `notification.timestamp` as ISO-8601 using `datetime.fromisoformat()`.
- Treat naive timestamps consistently with existing relative-time rendering by assigning
  `sase.core.time.get_timezone()`.
- Convert parsed datetimes to a numeric timestamp for comparison, avoiding naive-vs-aware comparison issues.
- Return `float("-inf")` for invalid timestamps so malformed legacy rows sort to the bottom of their bucket.
- Rely on Python's stable sort so rows with equal timestamps keep their existing store order.

The render logic remains:

1. Group each notification by `_section_for(n)`, storing `(original_index, notification)`.
2. Sort each non-empty group by parsed timestamp descending.
3. Emit the section header.
4. Emit notification options with `id=str(original_index)`.

Keeping option ids as original raw indices is important. Existing methods such as `_get_selected_index()`,
`_row_for_notification_index()`, `_replacement_notification_id_after_dismiss()`, jump hints, and action dispatch all use
those indices to retrieve `self._notifications[idx]`. We only want display order to change, not the modal's backing list
identity model.

## Interaction Implications

`initial_index` currently means "notification index in `self._notifications`", not "visual row number". That distinction
matters once visual order is sorted independently from storage order.

Update the modal constructor to accept `initial_index: int | None = None`:

- `None` means "highlight the first selectable notification in visual order". This should be the default for opening the
  panel normally, so the highlighted row matches the newest visible item in the top non-empty bucket.
- An integer keeps the existing identity-based behavior: highlight that notification index wherever it lands after
  sectioning and sorting. This preserves explicit call sites and tests that intentionally target a specific
  notification.

`on_mount()` should resolve the initial highlight through `_visual_notification_index_order()`:

1. If `initial_index` is an in-range integer, use it.
2. Otherwise, use the first index returned by `_visual_notification_index_order()`.
3. Translate the chosen notification index to an option-list row with `_row_for_notification_index()`.
4. Display the file for the actual highlighted notification, not merely `self._notifications[0]`.

This avoids a common UX bug where the newest item is visually on top but an older raw-index item remains selected.

## Tests

Update `tests/test_notification_modal.py`.

Add helper support to create notifications with custom timestamps, or set `.timestamp` directly in the tests.

Add focused tests:

1. `test_section_items_sort_newest_first_within_each_bucket`
   - Create priority, inbox, and muted notifications with mixed raw order and distinct timestamps.
   - Assert section order remains `hdr:priority`, priority rows newest-first, `hdr:inbox`, inbox rows newest-first,
     `hdr:muted`, muted rows newest-first.

2. `test_visual_notification_index_order_uses_recent_first_within_sections`
   - Use mixed timestamps across buckets.
   - Assert `_visual_notification_index_order()` returns indices in bucket order and newest-first inside each bucket.

3. `test_equal_timestamps_keep_existing_relative_order`
   - Use two notifications in the same bucket with identical timestamps.
   - Assert their relative order is the same as input order.

4. `test_invalid_timestamp_sorts_to_bottom_of_bucket`
   - Put one valid and one invalid timestamp in the same bucket.
   - Assert the valid timestamp row is displayed first.

5. `test_default_initial_highlight_uses_first_visual_notification`
   - Build a modal where raw index `0` is not the first visual row after sorting.
   - Mount it in a small Textual pilot or fake enough option-list behavior to assert the resolved highlight targets the
     first visual notification.

6. `test_explicit_initial_index_still_targets_that_notification`
   - Pass an integer `initial_index` for an older notification.
   - Assert the option-list row for that notification is highlighted even though it is not first visually.

Review existing tests that assert exact option ids:

- `test_sections_render_in_priority_inbox_muted_order`
- `test_visual_notification_index_order_skips_section_headers`
- jump-hint tests

Most currently use identical timestamps, so stable sorting should preserve their expectations. If any test implicitly
depends on raw order with different timestamps, update it to assert the new product behavior.

## Verification

After implementation:

1. Run focused tests:

   ```bash
   just test tests/test_notification_modal.py
   ```

2. Because this repo guidance requires it after code changes, run:

   ```bash
   just check
   ```

If this workspace has not been installed recently, run `just install` first as directed by `memory/short/workspaces.md`.

## Risks

- `initial_index` is raw-index based, while the display order will become timestamp based. This is already how the modal
  works with bucket headers: indexes identify notifications, not rows. The patch should avoid changing that contract.
- Malformed timestamps exist only defensively, but they should not crash the panel. Sorting invalid timestamps to the
  bottom is the least surprising fallback.
- Sorting in `_create_sectioned_options()` means `_visual_notification_index_order()` recomputes the same order whenever
  needed. That is acceptable for modal-sized lists and keeps the implementation localized.
