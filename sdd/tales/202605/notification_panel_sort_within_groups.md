---
create_time: 2026-05-11 13:09:01
status: done
prompt: sdd/prompts/202605/notification_panel_sort_within_groups.md
---
# Plan: Sort notifications within groups by timestamp (most recent first)

## Goal

Within the notification panel modal, sort the entries inside each severity group by `timestamp` descending so the most
recently received notification appears at the top of its group. Keep the fixed group order
(`priority → errors → inbox → muted`) and keep the section headers / spacer rows exactly as they are today.

## Background

The notification panel lives in `src/sase/ace/tui/modals/notification_modal*.py`. Notifications are loaded into
`self._notifications` and rendered by `NotificationOptionMixin._create_sectioned_options()`
(`src/sase/ace/tui/modals/notification_modal_options.py:130`), which:

1. Walks `self._notifications` in list order and assigns each one to a group via `_section_for()` (mute → errors →
   priority → inbox).
2. Iterates `SECTIONS` (the fixed order tuple in `notification_modal_constants.py`) and emits a header + each grouped
   entry in **insertion order**, with `option.id = str(original_index)`.

Today there is no per-group sort: rows appear in whatever order the loader produced them. The user wants newest-first
within each group while keeping the group order unchanged.

The `Notification` model (`src/sase/notifications/models.py:7`) already carries a `timestamp: str` (ISO-8601) field, and
`notifications/catalog.py` already has a battle-tested `_timestamp_sort_key` helper (line 35) that parses the ISO string
and forces a timezone — we should reuse the same parsing approach rather than rely on lexicographic string comparison
(timestamps can be tz-aware or naive and string sort breaks when offsets differ).

## Design

### Single change point

All visible ordering flows through `_create_sectioned_options()`. Sort each `groups[key]` list by timestamp descending
immediately after the grouping loop, before the header/option emission loop. Because
`_visual_notification_index_order()` already delegates to `_create_sectioned_options()` (line 174), jump-mode hint
ordering, marked-id traversal, and any other "visual order" consumers pick up the new sort for free — no second code
path to update.

### Sort key

Add (or reuse) a small helper that parses `notification.timestamp` to a tz-aware `datetime`, falling back gracefully for
malformed timestamps so a bad row can never crash the modal. Two reasonable options:

- **Reuse**: import `_timestamp_sort_key` from `src/sase/notifications/catalog.py` (rename to a public
  `timestamp_sort_key` in `models.py` or a new `sort.py` so it's no longer underscore-private). This keeps a single
  source of truth for "sort notifications by recency."
- **Local**: define a tiny inline `_sort_key` in `notification_modal_options.py`.

Recommendation: promote `_timestamp_sort_key` to a public helper in `sase.notifications` (e.g. `notifications/sort.py`
or extend `models.py`) and import it from both `catalog.py` and the modal. The catalog already does the exact "newest
first" sort users want here (`catalog.py:107`), so this aligns the two views' behavior under one definition.

### Preserve original indexes

The grouping tuple is `(original_index, notification)`. The sort must be by `notification.timestamp` only — the original
index is the row's stable identity used as `option.id` and must not change. (Sorting `groups[key]` does not renumber the
notifications themselves; it just reorders the `(idx, n)` pairs within each group's list.)

### Tie-breaking

If two notifications share an identical timestamp, fall back to original insertion order (stable sort handles this
automatically — Python's `sorted` is stable, so equal keys keep their relative order from the grouping loop). No extra
tie-breaker needed.

### Edge cases

- **Empty groups**: untouched — sort of an empty list is a no-op.
- **Single-entry groups** (common case for priority/errors): no behavioral change.
- **Malformed timestamps**: the parser returns a fallback (e.g. `datetime.min` in the project timezone) so the offending
  row sinks to the bottom of its group instead of raising. Match `catalog._timestamp_sort_key`'s existing behavior so
  the two surfaces handle bad data the same way.
- **Live updates (mark-read, dismiss, mute, unmute)**: these mutate `self._notifications` and then call
  `_rebuild_list()`, which re-invokes `_create_sectioned_options()`. The new sort runs on each rebuild, so the panel
  stays correctly ordered after every action without extra plumbing.
- **Jump hints (`_visual_notification_index_order`)**: already shares the ordering source, so one-key jump mode visits
  rows in the new visual order automatically.
- **Snoozed → expired transitions** that swap a row between groups: handled by the existing reload path; the row just
  lands in its new group's timestamp-sorted position.

## Files to change

1. **`src/sase/ace/tui/modals/notification_modal_options.py`** — add a `sorted(...)` call against `groups[key]` keyed on
   the parsed timestamp, descending, right after the grouping loop in `_create_sectioned_options()` (around line 143).
2. **`src/sase/notifications/...`** — extract `_timestamp_sort_key` into a reusable public helper (either in `models.py`
   next to `format_relative_time`, or in a new `notifications/sort.py`); update `catalog.py` to import it. Skip this if
   reviewers prefer the local helper approach.

## Tests

`tests/test_notification_modal_sections.py` covers section composition and ordering today but not intra-section order.
Add:

- **`test_inbox_group_sorted_newest_first`**: build a list with 3+ inbox notifications spanning several seconds/minutes
  and assert the rendered option order corresponds to descending `timestamp`.
- **`test_each_group_sorts_independently`**: mix priority, errors, inbox and muted with interleaved timestamps; assert
  each group is independently sorted newest-first while the overall section sequence remains
  `priority → errors → inbox → muted`.
- **`test_jump_visual_order_matches_sorted_render`**: verify `_visual_notification_index_order()` returns indexes in the
  new sorted order (guards against the second-code-path regression).
- **`test_malformed_timestamp_does_not_crash_and_sinks`**: include one entry with a non-parseable timestamp and assert
  it lands at the bottom of its group instead of raising.
- **`test_equal_timestamps_preserve_insertion_order`**: two notifications with byte-equal timestamps stay in their
  original relative order (stable sort guarantee).

If the shared-helper refactor lands, also add a unit test in `tests/test_notifications_sort.py` (or extend an existing
notifications test) asserting the helper handles tz-aware, tz-naive, and malformed inputs.

## Out of scope

- Changing the group order or removing groups (Q1 settled this).
- Changing what counts as priority / error / muted (`is_error`, `is_priority`, `notification.muted` semantics stay
  as-is).
- Persisting a user-configurable sort preference — this plan implements a single fixed policy (newest first within each
  group).
- Touching how the notification _catalog view_ renders (already newest-first; only relevant if we promote the shared
  helper).

## Verification

- Run `just check` in the workspace before reporting back.
- Manually exercise the panel: open notifications with mixed senders/ages, confirm visual order; mark-read / dismiss /
  mute one and confirm the panel re-sorts correctly on rebuild; trigger jump mode and confirm hint labels walk the
  entries top-to-bottom in the new visual order.
