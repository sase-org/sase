---
create_time: 2026-06-20 18:59:13
status: done
prompt: sdd/prompts/202606/log_panel_g_scroll.md
---
# Plan: Add `g` / `G` Top-Bottom Scrolling to the ACE Logs Panel

## Context

The ACE `,L` Logs panel is implemented by `src/sase/ace/tui/modals/log_modal.py`. It is a two-pane Textual modal:

- the left `OptionList` selects a log source;
- the right `VerticalScroll` with id `log-modal-detail-scroll` shows the selected source's rendered tail.

The modal already owns local bindings for list navigation, source cycling, refresh, and half-page detail scrolling:
`j`/`k`, `[`/`]`, `r`, and `ctrl+d`/`ctrl+u`. The app-level keymap already uses `g` / `G` for top/bottom scrolling on
normal ACE tabs, and `PlanApprovalModal` uses the same modal-local pattern for `g` / `G`.

Because this is presentation-only Textual behavior, no Rust core or backend change is expected. The TUI performance
guidance still applies: keep this as a synchronous in-memory scroll operation only, with no disk reads or refresh work
inside the key handlers.

## Product Behavior

When the Logs panel is open:

- pressing `g` scrolls the right-hand log content pane to the top;
- pressing `G` scrolls the right-hand log content pane to the bottom;
- the highlighted log source in the left pane does not change;
- existing `j`/`k`, `[`/`]`, `ctrl+d`/`ctrl+u`, `r`, and close behavior remain unchanged;
- selecting or refreshing a log source still resets the detail pane to the top, as it does today.

The visible footer hint should include the new top/bottom shortcuts so the modal advertises all scroll affordances.

## Implementation Outline

1. Update `LogModal.BINDINGS`.
   - Add `("g", "scroll_to_top", "Top")`.
   - Add `("G", "scroll_to_bottom", "Bottom")`.
   - Keep these modal-local rather than adding new configurable app keymap fields.

2. Add two `LogModal` actions targeting only the right content pane.
   - `action_scroll_to_top()` should query `#log-modal-detail-scroll` as a `VerticalScroll` and call
     `scroll_home(animate=False)`.
   - `action_scroll_to_bottom()` should query the same widget and call `scroll_end(animate=False)`.
   - Reuse the existing `ctrl+d` / `ctrl+u` detail-scroll structure; do not introduce background work, timers, or source
     reloads.

3. Update the footer copy in `LogModal.compose()`.
   - Extend the current scroll hint from `ctrl+d/u scroll` to include `g/G top/bottom` or equivalent concise wording.
   - No stylesheet change is expected unless the footer text no longer fits in the existing one-line area.

4. Keep global keymap configuration unchanged unless implementation reveals a real config contract.
   - `src/sase/default_config.yml` already defines app-level `g` / `G`, but modal-local bindings are not currently
     configurable through the keymap registry.
   - Do not add command-palette entries for these modal-local actions unless an existing modal-command convention is
     found during implementation.

## Tests

1. Extend `tests/ace/tui/test_log_modal.py`.
   - Add a direct binding guard proving `LogModal.BINDINGS` includes `g -> scroll_to_top` and `G -> scroll_to_bottom`.
   - Add a pilot test with enough log lines to make the right pane scrollable. Press `G`, verify the
     `#log-modal-detail-scroll` container reaches the bottom, then press `g` and verify it returns to the top.
   - Assert the left `OptionList.highlighted` value is unchanged across `g` / `G`.

2. Preserve existing behavior coverage.
   - Existing tests should continue proving initial selection, source cycling, refresh, half-page scroll, and dismissal.
   - Update assertions only where footer text or binding expectations change.

3. Run focused verification before broader checks.
   - Focused: `pytest tests/ace/tui/test_log_modal.py tests/ace/tui/test_log_panel_keymap.py`.
   - If footer copy affects the PNG snapshot, run `pytest tests/ace/tui/visual/test_ace_png_snapshots_log_panel.py` and
     inspect any diff before updating snapshots.
   - After source changes, run `just install` if needed and then `just check`, per project instructions.

## Risks and Edge Cases

- Textual key events may arrive while the left `OptionList` has focus. Binding these actions on the modal screen should
  match the existing `ctrl+d` / `ctrl+u` behavior, but the pilot test should confirm it.
- `scroll_end()` may need a post-refresh pause in tests before `scroll_y` settles. Prefer testing after
  `await pilot.pause()` rather than adding implementation delays.
- The footer is constrained to one line. If adding `g/G` makes it wrap or clip, shorten the wording rather than changing
  layout dimensions unnecessarily.
