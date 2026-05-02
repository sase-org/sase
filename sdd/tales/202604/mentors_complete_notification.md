---
create_time: 2026-04-25 17:22:52
status: done
prompt: sdd/prompts/202604/mentors_complete_notification.md
---
# Plan: Notification When All Mentors Finish For A ChangeSpec COMMITS Entry

## Goal

Introduce a new notification type that fires once per ChangeSpec COMMITS entry, when one of these two terminal
conditions is reached:

1. **Mentors-finished case** — every mentor that was started for the entry has reached a terminal status
   (`PASSED | COMMENTED | FAILED | DEAD | KILLED`).
2. **No-mentors case** — profile matching ran for the entry and zero mentor profiles matched, so no mentors will ever
   run.

The notification's `<enter>` action navigates to the **CLs** tab, selects the target ChangeSpec, and — if any mentor
left comments — pushes the **Mentor Review** modal.

## Product Context

Today the user has no positive signal that mentor review is "ready to look at". They either poll the CLs tab or wait
passively. The mentor-review keymap (`leader: review_mentors`) already exists and is the natural destination, but the
user has to remember to use it. Wiring a notification at the completion edge means the next mentor-review interaction is
one keypress away from arrival.

The no-match case matters because a ChangeSpec that triggers zero mentors looks identical from the outside to one whose
mentors haven't started yet. The user shouldn't have to wonder.

## Design Sketch

### New action type: `JumpToMentorReview`

The existing `JumpToChangeSpec` action navigates to a ChangeSpec but does not auto-open the Mentor Review modal — and
the new requirement of "open Mentor Review _if there are comments_" is stateful in a way that doesn't fit the generic
jump action. So we add a new action `JumpToMentorReview` with `action_data` keys:

- `changespec_name` — required, target ChangeSpec
- `project_file` — required, used by existing nav helper to switch project query if needed
- `entry_id` — required, the COMMITS entry whose mentors finished

The handler:

1. Calls `navigate_to_changespec_tab(app, changespec_name, project_file)` (existing helper at
   `src/sase/ace/tui/actions/agents/_notification_navigation.py:130`). This switches to the CLs tab, possibly retargets
   the query, and selects the row.
2. After successful navigation, looks up the matching MentorEntry on the now-selected ChangeSpec by `entry_id`. If any
   of its `status_lines` have status `COMMENTED` (or any reviewable status that the existing `_open_mentor_review`
   accepts), pushes `MentorReviewModal` using the same construction path that `_open_mentor_review` uses
   (`build_mentor_review_data` → `push_screen(MentorReviewModal(data), on_mentor_review_dismiss)`).
3. If there are no comments, the navigation alone is the complete behavior — the user lands on the ChangeSpec and sees
   the entry status. (This matches the "if any mentor comments were left" wording in the requirement.)

To minimise duplication, factor the inner body of `_open_mentor_review`
(`src/sase/ace/tui/actions/agent_workflow/_mentor_review.py:31`) so the modal-opening logic for a specific MentorEntry
is reusable from the notification handler — without recomputing "latest entry by max(entry_id)", since the notification
carries the exact entry_id it cares about.

### New sender: `notify_mentors_complete`

Add in `src/sase/notifications/senders.py`, modelled on `notify_sync_result`:

```python
def notify_mentors_complete(
    cl_name: str,
    project_file: str,
    entry_id: str,
    mentor_summary: str,   # e.g. "3/3 mentors finished (1 commented)" or "no mentor profiles matched"
    has_comments: bool,
    sender: str = "mentors",
) -> None
```

Builds a `Notification` with `action="JumpToMentorReview"`, `action_data={changespec_name, project_file, entry_id}`, and
`notes=[f"Mentors done for {cl_name} entry {entry_id}", mentor_summary]`. The `has_comments` flag is currently not part
of `action_data` (the handler re-reads truth from the live ChangeSpec at action time so the modal reflects current
state, not stale snapshot), but will be reflected in the notes line.

Register the new metric label `type="mentors_complete"` and bump test fixtures accordingly.

### Detection hook 1 — "all mentors terminal"

The polling loop in `check_mentors()` at `src/sase/ace/scheduler/mentor_checks.py:374` is the only place that already
iterates per ChangeSpec on a regular cadence and observes mentor state transitions. After Phase 1
(`_check_mentor_completion`) and before Phase 2/3, evaluate per (ChangeSpec, entry_id):

- Skip if the entry has zero `status_lines` (no mentors were ever started — handled by hook 2).
- Skip if any status_line is non-terminal (still running).
- Skip if we've already notified for this (changespec_name, entry_id, kind) — see idempotency.
- Otherwise emit `notify_mentors_complete(...)` and mark the idempotency state.

The summary string aggregates by counting status_lines per terminal status.

### Detection hook 2 — "no profiles matched"

`add_matching_profiles_upfront()` in `src/sase/ace/scheduler/mentor_profile_matching.py:420` already detects the
zero-match case (logs "Mentor matching: 0 new profiles matched..."). Two complications:

- It runs every poll cycle, so we cannot fire on every observation.
- It only fires the no-match log for the _current latest entry_; we want to notify exactly once per (ChangeSpec,
  entry_id) where the conclusion is permanent.

The conclusion is permanent only once the entry's hooks are all ready (otherwise additional matches could appear). In
practice the function already runs on every cycle, so we can defer the no-match notification to the same place as hook 1
— gated on `_all_non_skip_hooks_ready(changespec, entry_id)` returning True AND the absence of any MentorEntry with
status_lines for that entry. This keeps both notification triggers in one function and shares idempotency.

### Idempotency

Both triggers need a "have we notified yet for this (changespec_name, entry_id)?" flag that survives process restarts.

**Recommended: sidecar JSON file.** `~/.sase/notifications/mentors_complete.json` — a single dict mapping
`{"<project_file>::<changespec_name>::<entry_id>": "<iso_timestamp>"}`. Read-modify-write under fcntl lock (mirroring
`notifications/store.py`). Pros: zero schema changes to ChangeSpec / MentorEntry; survives `.gp` archival; trivially
testable.

**Alternative considered: add `notified_completion: bool` to `MentorEntry`.** Cleaner data model, but requires migrating
all `.gp` parsers/serialisers and doesn't help the no-match case (no MentorEntry exists). Rejected.

The sidecar lives outside the `.gp` files and doesn't pollute display.

A small helper module — e.g. `src/sase/notifications/mentor_completion_marker.py` — exposes `is_notified(...)` and
`mark_notified(...)` and is the only consumer/producer.

### Where the hook is wired

A new helper `_check_mentor_completion_notifications(changespec, log)` is called from `check_mentors` between Phase 1.5
(kill stale) and Phase 2 (add matching profiles upfront). It:

1. Determines the latest non-proposal entry_id (same logic as `_get_mentor_profiles_to_run`).
2. Fast-exits if hooks aren't all ready (the answer "no mentors will run" isn't decided yet).
3. Inspects the MentorEntry for that entry_id; classifies as `mentors-finished`, `no-mentors`, or `still-running`.
4. For terminal classifications, calls `mark_notified` and `notify_mentors_complete` if not already marked.

This keeps all completion-notification logic in `mentor_checks.py` next to the existing mentor lifecycle code.

## Files To Touch

- **`src/sase/notifications/senders.py`** — add `notify_mentors_complete`.
- **`src/sase/notifications/mentor_completion_marker.py`** _(new)_ — sidecar idempotency helpers.
- **`src/sase/ace/scheduler/mentor_checks.py`** — add `_check_mentor_completion_notifications`, call from
  `check_mentors`. Returns updates list, appended to existing updates.
- **`src/sase/ace/tui/actions/agents/_notification_handlers.py`** — add `handle_jump_to_mentor_review`.
- **`src/sase/ace/tui/actions/agents/_notifications.py`** — register dispatch for `JumpToMentorReview` (around line
  400-413 where existing actions are mapped).
- **`src/sase/ace/tui/modals/notification_modal.py`** — add `JumpToMentorReview` to `_ACTION_BADGES` (line ~30) so the
  notification renders with a badge.
- **`src/sase/ace/tui/actions/agent_workflow/_mentor_review.py`** — extract the modal-opening body of
  `_open_mentor_review` into a helper that accepts an explicit MentorEntry, so the new notification handler can call it
  without duplicating modal-construction logic.
- **`tests/test_notification_senders.py`** _(or alongside existing notification tests)_ — sender emits correct
  action/action_data.
- **`tests/test_notification_mentor_completion_marker.py`** _(new)_ — sidecar idempotency.
- **`tests/test_mentor_checks.py`** _(if exists, else new)_ — golden cases:
  - All mentors terminal → notification once, then no further notifications.
  - No profiles matched + hooks ready → notification once.
  - No profiles matched but hooks not ready → no notification yet.
  - Mid-run (some mentors still RUNNING) → no notification.
- **`tests/test_notification_handlers.py`** _(or co-located)_ — `JumpToMentorReview` opens modal iff the entry has
  commented mentors; navigates regardless.

## Open Questions / Tradeoffs

1. **What counts as "comments left" for the auto-open?** The existing `_open_mentor_review` has logic at
   `src/sase/ace/tui/actions/agent_workflow/_mentor_review.py:49` that gates on certain statuses
   (COMMENTED/FAILED/RUNNING/PASSED). The notification handler should reuse the same gate rather than inventing one —
   propose: extract the gate function and call from both sites.

2. **Should the no-match case still navigate to the ChangeSpec?** The requirement says yes — the user lands on the CLs
   tab with the ChangeSpec selected, but no modal is pushed (because no comments exist). This naturally falls out of the
   design above.

3. **What `sender` string?** New string `"mentors"` — keeps notification grouping/filtering coherent with the other
   senders (`"sync"`, `"plan"`, `"hitl"`, `"axe"`).

4. **Telegram/external delivery.** All notifications go through the same store, so the plugin-side delivery
   (`sase-telegram`, etc.) inherits the new type for free as long as the Notification dataclass shape is unchanged —
   which it is. No plugin-side work required.

5. **Race between Phase 1 marking mentors DEAD and the notification check.** Hook order in `check_mentors` is: Phase 1
   (mark DEAD) → Phase 1.5 (kill stale) → **new completion-notify phase** → Phase 2/3. So the notification phase reads
   the just-updated state. Good.

## Acceptance

- New notification appears in the notification modal with a badge.
- `<enter>` switches to CLs, selects the ChangeSpec, opens Mentor Review iff comments exist.
- The notification fires exactly once per (ChangeSpec, entry_id) across restarts.
- No-match case fires only after hooks are ready.
- `just check` passes (lint + mypy + tests).
