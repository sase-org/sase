---
create_time: 2026-06-29 10:20:25
status: done
---
# Move Updates Badge Left of Model Indicator

## Goal

Move the ACE top-bar indicator for available SASE core/plugin updates out of the far-right corner and place it
immediately to the left of the model indicator, while keeping it in the top-right indicator cluster and preserving its
existing behavior.

## Current Understanding

- The ACE TUI top bar is composed in `src/sase/ace/tui/app.py` inside `AceApp.compose()`.
- `#tab-bar` has `width: 1fr` in `src/sase/ace/tui/styles.tcss`, so every widget yielded after `TabBar(id="tab-bar")`
  forms the right-aligned indicator cluster.
- The current right-cluster yield order is: `TaskIndicator`, `LLMOverrideIndicator`, `InactiveIndicator`,
  `StashedPromptsIndicator`, `NotificationIndicator`, `UpdatesAvailableIndicator`.
- Because `UpdatesAvailableIndicator(id="updates-indicator")` is yielded last, it renders at the far right whenever
  updates are available.
- Update availability state is already correctly decoupled from layout: `UpdateToastMixin` and admin-center dismissal
  refreshes target `#updates-indicator`, and `UpdatesAvailableIndicator` owns the count, tooltip, click handler, and
  hidden-at-zero behavior.

## Implementation Plan

1. Reorder only the top-bar composition in `AceApp.compose()`.
   - Move `UpdatesAvailableIndicator(id="updates-indicator")` so it is yielded immediately before
     `LLMOverrideIndicator(id="llm-override-indicator")`.
   - Keep it after `TaskIndicator(id="task-indicator")` so task activity remains the leftmost transient operational
     badge in the right cluster.
   - Leave the indicator widget implementation, click action, tooltip, and update-status refresh code unchanged.

2. Keep CSS unchanged unless testing reveals an actual layout issue.
   - The existing `width: auto` and `content-align: right middle` rules apply equally to the new position.
   - The `#tab-bar { width: 1fr; }` spacer still anchors the whole group at the top right.

3. Add a focused regression test for the top-bar order.
   - Add a small ACE app/widget test that mounts the app and inspects `#top-bar` child IDs.
   - Assert that `updates-indicator` appears before `llm-override-indicator`, and preferably assert the full
     right-cluster order so future reorders are intentional.
   - This test should not depend on network, package update checks, or visual rendering.

4. Review visual snapshot impact.
   - `tests/ace/tui/visual/test_ace_png_snapshots_update_toast.py` intentionally drives a nonzero update status, so its
     PNG snapshot may move the update badge.
   - If the snapshot fails only because of the intended top-bar badge movement, refresh that golden through the existing
     visual snapshot update workflow.
   - Do not change unrelated visual snapshots.

5. Verify.
   - Run `just install` first because numbered SASE workspaces are ephemeral.
   - Run the focused tests for the touched behavior, including the new order test and update-toast tests.
   - Run the relevant visual snapshot test if needed to confirm/update the top-bar rendering.
   - Run `just check` before finishing, because this change touches repo files outside the documented exceptions.

## Expected Outcome

When updates are available, the top-right cluster should read with the updates badge immediately to the left of the
model indicator instead of at the far right. Existing update detection, click-to-open Updates tab behavior, startup
toast behavior, and admin-center refresh behavior should remain unchanged.
