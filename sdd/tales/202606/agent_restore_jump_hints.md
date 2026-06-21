---
create_time: 2026-06-21 09:14:10
status: done
prompt: sdd/prompts/202606/agent_restore_jump_hints.md
---
# Agent Restore Jump Hints Plan

## Context

The Agent Restore modal is a two-pane `SavedAgentGroupRevivalModal` backed by a single `OptionList`. It currently
supports linear navigation (`j/k`, arrows, Ctrl-N/Ctrl-P), Enter activation, and PgDn/load-row pagination. The recently
polished left pane now contains disabled section headings and separators plus selectable rows for saved groups, recent
dismissals, load-more, and custom search.

The requested behavior is to add the apostrophe keymap to this panel so users can jump to different rows using one-key
hints. The nearest existing pattern is `NotificationModal`: apostrophe enters a transient jump mode, visible rows are
rebuilt with hint markers, the next key moves the highlight, Escape cancels, and Enter remains the activation path. That
behavior should be adapted rather than reimplemented from scratch.

The TUI performance memory calls out two relevant constraints:

- Do not add blocking work to key handlers.
- Guard against excessive rebuilds or selection echoes. This feature can stay cheap because hint mode only rebuilds the
  small modal option list when entering/exiting jump mode or after a jump.

## Product Behavior

Add `'` / `apostrophe` support to Agent Restore:

- Pressing apostrophe enters row-jump mode and decorates selectable rows with hint markers.
- Pressing a displayed hint key moves the list highlight to that row and keeps the modal open.
- Pressing Enter after a jump activates the highlighted row exactly as it does today.
- Pressing Escape while jump mode is active cancels jump mode without closing the modal.
- Pressing apostrophe again while jump mode is active jumps back to the previously highlighted row when one exists;
  otherwise it should behave like selecting the first visible hinted row, matching the notification modal.
- Invalid jump keys should exit jump mode, remove hints, and leave the current highlight unchanged.

Hint targets should include every enabled/selectable row in visual order:

- Saved-group rows.
- The load-more row, when present.
- Recent-dismissal rows.
- The custom-search row.

Hint targets should exclude disabled headings, disabled empty-state rows, and disabled blank separators.

## Technical Design

Use the existing generic jump-hint helper:

- Import `build_jump_hint_maps` and `normalize_jump_key` from `sase.ace.tui.actions.navigation.jump_hints`.
- Reuse the same hint character sequence already used by notification and agents-tab jump flows.

Keep the implementation local to the Agent Restore modal and its row renderer:

- Add an apostrophe binding to `SavedAgentGroupRevivalModal.BINDINGS`.
- Track modal-local transient jump state:
  - jump mode active boolean
  - hint-to-option-id map
  - option-id-to-hint map
  - last selected option id for back-jump behavior
- Add a helper that returns selectable option ids in current visual order by building or inspecting the current option
  list while skipping disabled rows.
- Extend `_create_options()` to accept an optional hint map keyed by option id. The normal path stays unchanged; jump
  mode passes hint markers through.
- Add a rendering helper for row hint prefixes. Prefer a common wrapper that can prefix any selectable row label with
  `[N] ` while preserving the existing styled `Text`, no-wrap, and overflow behavior.
- Rebuild the option list when entering and leaving jump mode, preserving the current highlighted option id rather than
  only the numeric row index. This is important because disabled headings/separators and the load-more row make row
  positions less stable after pagination.
- Add `on_key()` to intercept jump-mode keys before modal bindings dispatch. Normalize keys with `normalize_jump_key()`
  so uppercase hint characters work.

Preview handling:

- A successful jump should set the `OptionList.highlighted` row for the target option id and call the same preview
  update path used by normal highlight movement.
- Jumping to `load-more` should show the load-more preview only; it must not load another page until Enter is pressed.
- Jumping to `custom-search` should show the custom-search preview only; it must not dismiss until Enter is pressed.

Footer copy:

- Normal footer should mention the jump key, for example: `j/k: navigate | ': jump | Enter: revive/open | ...`
- Jump-mode footer should temporarily show a compact instruction such as: `JUMP ' back <esc> cancel` or
  `JUMP ' first <esc> cancel`.
- Exiting jump mode restores the existing count/load-more/footer text.

## Implementation Steps

1. Add Agent Restore jump state and apostrophe binding in `saved_agent_group_revival_modal.py`.
2. Add option-id based helpers:
   - current highlighted option id
   - row lookup by option id
   - selectable visual option ids
   - rebuild with preserved highlighted option id
3. Extend option construction so jump hints can be injected for selectable rows only.
4. Add jump-mode actions:
   - `action_jump_to_entry`
   - `_handle_entry_jump_key`
   - `_jump_to_option_id`
   - `_exit_entry_jump_mode`
   - `_clear_entry_jump_hints`
5. Update hint/footer text for normal and jump modes.
6. Ensure `_load_more()` exits jump mode or rebuilds without stale hint maps after pagination changes the option set.
7. Keep all work synchronous and in-memory; do not add file I/O, subprocesses, async waits, or background refreshes to
   key handlers.

## Tests

Add focused unit/pilot coverage under `tests/ace/tui/modals/test_saved_agent_group_revival_modal.py`:

- Apostrophe enters jump mode and injects hints only on enabled rows.
- Hint key moves highlight to a saved-group row and refreshes the preview without dismissing.
- Hint key can move to a recent-dismissal row.
- Hint key can move to load-more without invoking the loader until Enter.
- Hint key can move to custom-search without dismissing until Enter.
- Escape cancels jump mode without dismissing.
- Invalid keys cancel jump mode and keep the current highlight.
- Apostrophe inside jump mode returns to the previous highlighted row, or first hinted row when no previous row exists.
- Uppercase hints work through `on_key()` normalization.

Add/adjust integration coverage if needed:

- A pilot test pressing `apostrophe`, a hint key, and then Enter in the real modal should verify that highlight
  navigation and activation compose correctly.

Visual snapshots:

- Do not update the existing normal/empty/load-more/rich snapshots unless the normal-state footer copy changes enough to
  require it.
- If the hint markers materially affect layout risk, add a separate jump-mode PNG snapshot rather than folding transient
  hint mode into the existing normal snapshots.

## Verification

Run the focused checks first:

- `./.venv/bin/python -m pytest tests/ace/tui/modals/test_saved_agent_group_revival_modal.py`
- Relevant revival e2e/pilot tests if new coverage lands there.
- Saved-group visual snapshot test if the footer or row layout goldens change.

Then run the repo-required gates:

- `just install`
- `just check`

If `just check` still hits the previously observed unrelated directive fanout failures, rerun the failing subset
separately and report the separation clearly.

## Risks and Mitigations

- **Stale row indexes after load-more:** use option ids as jump targets and rebuild/highlight by option id.
- **Disabled rows receiving hints:** derive targets from enabled rows only.
- **Accidental activation on jump:** keep jump behavior highlight-only and leave Enter as the sole activation path.
- **Footer/hint stale state after pagination:** clear jump maps when rebuilding normal options and after load-more.
- **TUI responsiveness regression:** keep all jump work in-memory, limited to a small option-list rebuild on mode
  transitions.
