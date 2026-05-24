---
create_time: 2026-05-23 21:28:34
status: done
prompt: sdd/prompts/202605/memory_notification_actions.md
---
# Plan: Memory Proposal Notification Actions

## Problem

`sase memory write --notify` already creates a `memory.proposed` notification with `action="memory_review"` and
`action_data={"proposal_id": ...}`, but the ACE notification flow does not dispatch that action. As a result, selecting
the notification shows the row/badge but does not open the memory review experience. The sender also does not tag these
notifications as `memory`, so they cannot be filtered through the notification tag UI.

The goal is to make memory proposal notifications behave like first-class actionable notifications:

- Selecting the notification in ACE should launch the same `MemoryReviewTuiApp` used by bare `sase memory review`.
- The launched review app should focus the proposed memory when possible.
- The notification should carry the normalized `memory` tag.

## Current Shape

Relevant files:

- `src/sase/notifications/senders.py`
  - `notify_memory_proposed()` constructs the notification.
  - It already sets `sender="memory.proposed"`, `action="memory_review"`, and proposal id action data.
  - It does not set `tags`.
- `src/sase/notifications/pending_actions.py`
  - Already maps `memory_review` to the pending-action kind `memory_review`.
- `src/sase/ace/tui/modals/notification_modal_constants.py`
  - Already renders the `[memory]` action badge for `memory_review`.
- `src/sase/ace/tui/actions/agents/_notification_modal_flow.py`
  - Dispatches known notification actions after the notification modal closes.
  - Does not currently dispatch `memory_review`.
- `src/sase/ace/tui/actions/agents/_notification_handlers.py`
  - Hosts simple ACE notification handlers that either navigate or suspend ACE while running another terminal command.
- `src/sase/memory/cli_review.py`
  - Bare `sase memory review` launches `MemoryReviewTuiApp().run()`.
- `src/sase/memory/review_tui/app.py`
  - The review TUI currently defaults to the first pending proposal.

## Design

1. Keep the existing notification action string, `memory_review`. It is already present in tests, badges,
   catalog/pending-action indexing, and pending-action storage.

2. Add a `handle_memory_review(app, notification)` notification handler. The handler will:
   - read `proposal_id` from `notification.action_data`;
   - warn and return `False` when it is missing;
   - suspend the ACE app and instantiate `MemoryReviewTuiApp` directly, rather than shelling out to
     `sase memory review`;
   - pass the proposal id as an initial selection hint;
   - return `True` after the review TUI exits.

   Suspending ACE follows the existing terminal action pattern used by editor, tmux, and error-report flows. Directly
   constructing `MemoryReviewTuiApp` guarantees the action uses the same TUI implementation as the CLI.

3. Add an optional initial proposal selection to `MemoryReviewTuiApp`. Add an `initial_proposal_id: str | None = None`
   constructor argument and seed `_selected_id` from it. The existing `_reload()` logic will retain that selection if
   the proposal is still in the pending set, or gracefully fall back to the first pending proposal if it has already
   been reviewed.

4. Wire `memory_review` into ACE notification dispatch. Update the re-export module and `_show_notification_modal()`
   dispatch chain so selecting a memory notification calls `handle_memory_review()`.

5. Add the `memory` tag at send time. Update `notify_memory_proposed()` to set
   `tags=normalize_notification_tags(["memory"])`.

## Tests

Add or update focused tests:

- `tests/notification_store/test_senders.py`
  - Extend `TestNotifyMemoryProposed` to assert `notification.tags == ["memory"]`.
- `tests/main/test_memory_review_tui.py`
  - Add coverage that `MemoryReviewTuiApp(initial_proposal_id=...)` opens with the matching pending proposal selected.
- New ACE notification handler test, likely `tests/ace/tui/test_memory_review_notification_action.py`
  - Fake app with `suspend()` context manager and `notify()` collection.
  - Patch `MemoryReviewTuiApp` in the handler module.
  - Assert the handler constructs the app with the notification proposal id and runs it under suspend.
  - Assert missing `proposal_id` warns and returns `False`.

Run targeted tests first:

```bash
uv run pytest tests/notification_store/test_senders.py \
  tests/main/test_memory_review_tui.py \
  tests/ace/tui/test_memory_review_notification_action.py
```

Then, because this changes repo files, run the project-required check:

```bash
just install
just check
```

## Risks and Mitigations

- Nested Textual apps can be fragile if run without suspending the parent app. The handler will use
  `with app.suspend(): MemoryReviewTuiApp(...).run()` to keep ACE out of the terminal while the review TUI owns it.
- A notification can outlive its pending proposal. The TUI selection hint should be best-effort; existing pending-only
  filtering will fall back cleanly.
- This should not modify canonical memory files or memory instruction files. Only notification, TUI, and test code
  should change.
