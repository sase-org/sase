---
create_time: 2026-05-29 08:17:28
status: done
prompt: sdd/prompts/202605/notification_tabs.md
---
# Notification Modal Tabs Plan

## Goal

Update the ACE TUI notification modal so notifications are organized only by top-level tabs, not by status sections
inside each tab.

The desired tab taxonomy is:

- `HITL`: plan approval and user question notifications, and the existing workflow HITL action if present.
- `Errors`: error notifications currently identified by the shared notification error classifier.
- Existing tag tabs such as `General`, `done`, `review`, and `memory`, with labels adjusted so the first displayed
  character is capitalized.

Rows inside a selected tab should be a flat list, sorted by recency, with no `PRIORITY`, `ERRORS`, `INBOX`, or `MUTED`
headers or spacer rows.

## Current Shape

- `src/sase/ace/tui/modals/notification_modal_tags.py` builds tabs from notification tags. Untagged notifications become
  `General`; `done` is pinned before other tags; other tags sort alphabetically.
- `src/sase/ace/tui/modals/notification_modal_options.py` then filters by active tag and groups rows into status
  sections using `is_priority`, `is_error`, and muted state.
- `src/sase/ace/tui/modals/notification_modal.py` assumes disabled header rows can appear, so selection and activation
  avoid option IDs beginning with `hdr:`.
- Tests in `tests/test_notification_modal_sections.py`, `tests/test_notification_modal_mark_and_tabs.py`, and
  `tests/ace/tui/test_agents_tab_completion_dismiss_e2e.py` encode the current section headers and tag behavior.

## Proposed Design

1. Replace the modal's status-section rendering with flat active-tab rendering.
   - Keep row labels, badges, mute dimming, mark state, snooze text, file counts, and tag badges.
   - Sort all visible rows for the active tab by `timestamp_sort_key(...), reverse=True`.
   - Keep option IDs as original notification indexes so existing selection, dismissal, mark, and jump behavior remains
     stable.

2. Extend tab classification in `notification_modal_tags.py`.
   - Add a helper that returns the effective modal tab keys for a notification.
   - Route `PlanApproval`, `UserQuestion`, and `HITL` actions to a synthetic `hitl` tab labeled `HITL`.
   - Route `is_error(notification)` notifications to a synthetic `errors` tab labeled `Errors`.
   - Preserve existing tag-based tabs for all other notifications.
   - Preserve `General` for notifications with no synthetic tab and no display tags.

3. Define clear tab ordering.
   - Show `HITL` first when present because these need user action.
   - Show `Errors` next when present.
   - Show `General` next when present.
   - Keep `Done` pinned before remaining existing tag tabs.
   - Sort remaining tags alphabetically by their displayed label.

4. Capitalize existing tab labels.
   - Convert labels derived from stored tags by uppercasing the first displayed character only: `done` -> `Done`,
     `review` -> `Review`.
   - Leave all-uppercase/synthetic labels as intended: `HITL`, `Errors`, `General`.
   - Do not change stored notification tags or CLI/store normalization.

5. Update modal method names only where helpful.
   - Keep compatibility wrappers if tests or nearby code call `_create_sectioned_options`; otherwise rename internally
     to a flat-list name and update callers.
   - Remove imports/constants that only supported section headers if no longer needed.
   - Keep defensive header-ID checks harmless where they simplify the patch, but prefer removing dead header-specific
     assertions from tests.

6. Update tests around the new product contract.
   - Replace section-order tests with flat-list tests.
   - Add/adjust tests for `HITL` tab membership, `Errors` tab membership, and capitalized existing tab labels.
   - Update visual-order and jump-hint tests to expect no header rows.
   - Update completion-dismissal tests so failed-agent `ViewErrorReport` notifications appear under `Errors` rather than
     `General`, while successful completions remain under `Done`.

## Verification

Run focused tests first:

```bash
uv run pytest tests/test_notification_modal_sections.py tests/test_notification_modal_mark_and_tabs.py tests/ace/tui/test_agents_tab_completion_dismiss_e2e.py
```

Because repository instructions require it after file changes, run:

```bash
just install
just check
```
