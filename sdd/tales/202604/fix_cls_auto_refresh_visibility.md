---
create_time: 2026-04-29 13:08:12
status: done
prompt: sdd/prompts/202604/fix_cls_auto_refresh_visibility.md
---
# Plan: Restore CLs Tab Auto-Refresh Visibility

## Problem

The CLs tab still computes and appends the auto-refresh countdown in `ChangeSpecInfoPanel`, but the widget is
constrained to one row inside the dynamically sized left list column. The newer grouping badge
(`[group: by project (o)]`) is rendered before the countdown. In the provided snapshot, the visible info text already
consumes the list column width, so the appended `(auto-refresh in Ns)` segment is clipped off the right edge.

## Goals

- Make the auto-refresh countdown visible on the CLs tab again.
- Preserve the existing CL count, hidden-count, fold-state, and grouping-mode signals.
- Avoid moving global refresh keybindings into the conditional footer; ACE guidance says global actions belong in help,
  while this countdown is status telemetry.
- Keep the fix local to the CL info panel and its layout unless testing shows the app-level sizing also needs a small
  update.

## Approach

1. Change `ChangeSpecInfoPanel` so its content has a predictable visible place for the countdown when auto-refresh is
   enabled.
   - Prefer a compact two-line layout: first line for ChangeSpec position/count/hidden/fold status, second line for
     grouping and `(auto-refresh in Ns)`.
   - If auto-refresh is disabled, omit the countdown as today.
   - Keep the grouping key hint visible on the second line because it is an active mode affordance, not a conditional
     footer binding.

2. Update the CL info panel CSS/layout to allow the second line.
   - Raise `#info-panel` from max-height 1 to a fixed/auto height that can display two lines.
   - Leave the list and ancestor panels using the remaining `1fr` height so the main layout continues to fit.

3. Update tests around `ChangeSpecInfoPanel`.
   - Add/adjust assertions that the countdown is present after `update_countdown`.
   - Add a focused assertion for the new line structure so the countdown cannot silently move off-screen behind other
     status badges again.
   - Keep existing grouping badge tests valid by checking plain text rather than exact one-line formatting where
     possible.

4. Verify narrowly first, then broadly.
   - Run the focused info-panel tests.
   - Run the ACE TUI widget tests that import `ChangeSpecInfoPanel`.
   - Because this repo requires it after file edits, run `just install` if needed and then `just check` before
     finishing.

## Risks and Mitigations

- A two-line info panel reduces the CL list by one row. This is acceptable because it restores a live status signal
  without disturbing detail/footer behavior.
- Exact text snapshots could break if any tests assumed a one-line panel. Prefer minimal test changes scoped to the
  affected widget.
- If Textual treats `height: auto` unexpectedly for multi-line `Static`, use an explicit `height: 2` with
  `max-height: 2`.
