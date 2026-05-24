---
create_time: 2026-05-24 09:46:10
status: done
prompt: sdd/prompts/202605/notification_tag_tab_isolation.md
---
# Notification Tag Tab Isolation Plan

## Context

The recent notification tag feature is already wired through the notification model, CLI creation/listing, and the ACE
notification modal:

- `Notification.tags` is persisted as normalized string tags.
- `NotificationModal` builds tag tabs through `src/sase/ace/tui/modals/notification_modal_tags.py`.
- `NotificationOptionMixin._create_sectioned_options()` filters rows only when `_active_notification_tag` is not `None`.
- Because the default tab is represented as `None` and currently means "All", tagged notifications still appear in the
  default tab as well as in their tag tab.

The requested behavior is stricter: a tagged notification should be visible only on the notification panel tab that
corresponds to its tag.

## Product Contract

Implement tag tabs as partitions for modal visibility:

- Notifications with no displayable tags appear in the default untagged tab.
- Notifications with tags do not appear in the default tab.
- A notification appears in a tag tab only when that notification has the corresponding tag.
- A multi-tag notification appears in each matching tag tab, but never in the default tab. This preserves the existing
  multi-value `tags` model without inventing a new primary-tag concept.
- Existing notification actions, section grouping, row sorting, jump hints, marking, muting, snoozing, and dismiss
  behavior continue to operate on the rows visible in the active tab.

I will relabel the default tab from `All` to `General`, since it will no longer be an unfiltered view. If there are no
untagged notifications, the modal should open on the first available tag tab rather than showing an empty default tab.

## Implementation Approach

1. Centralize tab membership in `src/sase/ace/tui/modals/notification_modal_tags.py`.

   Add a helper such as `notification_matches_tag_tab(notification, tag)`:
   - `tag is None` means the default General tab and matches only notifications whose normalized/displayable tag list is
     empty.
   - A string tag matches only when it appears in `notification_display_tags(notification)`.

   Update `build_notification_tag_tabs()` so the default tab count is the number of untagged notifications, not the
   total notification count. Keep `done` pinned before alphabetic tags.

2. Make the modal choose a valid starting tab.

   In `NotificationModal.__init__`, initialize `_active_notification_tag` to the first computed tab:
   - `None` when there are untagged notifications.
   - The first tag, usually `done` when only tagged notifications exist.
   - `None` when there are no notifications.

   Update `_coerce_active_notification_tag()` and `_switch_notification_tag_tab()` so an invalid or disappearing active
   tab falls back to the nearest existing tab, then to the first current tab, rather than blindly returning to `None`.

3. Apply the new membership helper when rendering rows.

   Replace the current `active_tag is not None` filter in `NotificationOptionMixin._create_sectioned_options()` with the
   centralized helper. This makes the default tab exclude tagged rows and keeps section headers/counts scoped to the
   active tab.

4. Preserve local modal behavior.

   Because visual order, jump hints, marking, and dismiss replacement are all derived from
   `_create_sectioned_options()`, they should naturally follow the active tab after the filter change. I will still
   check the edge cases where dismissing the last row in a tag removes that tab.

## Tests

Update and add focused tests in the existing modal test files:

- `tests/test_notification_modal_sections.py`
  - default General tab counts only untagged notifications;
  - tagged notifications are excluded from the default tab;
  - specific tag tabs still show only matching rows;
  - when all notifications are tagged, the initial active tab is the first tag and the modal is not empty;
  - multi-tag rows appear in each matching tag tab and not in General.

- `tests/test_notification_modal_actions.py`
  - bracket navigation cycles through the new tab order when no General tab is present;
  - dismissing the last row in an active tag still lands on a valid remaining tab.

- `tests/ace/tui/test_agents_tab_completion_dismiss_e2e.py`
  - update expectations that previously treated the default tab as an unfiltered "All" view;
  - verify completion notifications tagged `done` are only visible in `done`, while unrelated untagged plan/question
    rows remain in General.

Run targeted tests first:

```bash
pytest tests/test_notification_modal_sections.py tests/test_notification_modal_actions.py tests/ace/tui/test_agents_tab_completion_dismiss_e2e.py
```

Then run the repository-required validation after code changes:

```bash
just install
just check
```

## Risks And Boundaries

- This is presentation behavior in the ACE Textual modal, so I do not expect a Rust core change. Notification
  persistence and CLI filtering already have tag-aware behavior and should remain unchanged.
- Removing the unfiltered `All` view is intentional for the requested isolation. If a future product need wants both
  isolation and an explicit global overview, that should be a separate non-default `Everything` tab so tagged rows are
  not mixed into General.
- The only ambiguous case is a notification with multiple tags. This plan treats each tag as a valid corresponding tab.
  If the desired behavior is exactly one tab per notification, the data model needs an explicit primary notification tag
  rather than overloading the existing list of tags.
