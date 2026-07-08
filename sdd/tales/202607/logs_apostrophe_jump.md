---
create_time: 2026-07-07 22:38:26
status: done
prompt: sdd/prompts/202607/logs_apostrophe_jump.md
---
# Add apostrophe entry-jump support to Admin Center Logs

## Goal

Make the SASE Admin Center Logs tab support the existing apostrophe-style entry jump interaction so a user can press
`'`, see one-key hints beside log source rows, and jump directly to a specific Logs entry. The behavior should feel
consistent with the rest of ACE while staying local to the Admin Center modal.

## Current behavior and constraints

- The main ACE app already has `jump_to_entry` on `apostrophe`, backed by `build_jump_hint_maps()` and
  `normalize_jump_key()` in `src/sase/ace/tui/actions/navigation/jump_hints.py`.
- That main-app jump mode only covers top-level ACE tabs such as Agents, ChangeSpecs, and AXE. It does not run while the
  Admin Center modal owns focus.
- The Logs tab is implemented by `LogsPane` in `src/sase/ace/tui/modals/logs_pane.py`. It already has a bounded list of
  log sources, an `OptionList`, and off-thread loading for source metadata/detail content.
- TUI performance rules matter here: keypress handling must not add disk I/O or expensive recomputation. Existing log
  source metadata is read off-thread in `_build_log_pane_load_result()`, so jump rendering should reuse cached option
  labels rather than restatting log files during each jump keypress.
- No default keymap change is needed. The action already exists globally and the modal family already uses local
  hardcoded bindings for picker-style jump modes.

## Implementation plan

1. Add LogsPane-local jump state.
   - Track whether Logs jump mode is active.
   - Track hint-to-source-index and source-index-to-hint maps using the shared `build_jump_hint_maps()` helper.
   - Track a small back stack of prior selected source indices so in-mode `'` can behave like "first/back" instead of
     only selecting literal hint keys.

2. Cache rendered source rows from the worker result.
   - Store the `result.options` rows already produced off-thread by `_build_log_pane_load_result()`.
   - Rebuild the `OptionList` from this cache when entering or leaving jump mode.
   - Prefix cached row labels with a styled jump marker, for example `[1]`, only while jump mode is active.
   - Avoid calling `_source_label()`, `_format_mtime()`, or other filesystem stat helpers from key handlers.

3. Add LogsPane jump actions and key handling.
   - Bind/intercept `apostrophe` in LogsPane.
   - On first `'`, allocate hints for the currently loaded source rows, show hint prefixes, and update the Logs footer
     to a jump-mode hint line.
   - While jump mode is active, normalize printable keys with `normalize_jump_key()`.
   - `escape` cancels jump mode without moving.
   - A valid hint clears jump mode, pushes the current source onto the back stack when the target differs, highlights
     the target, and starts the existing off-thread detail load for that source.
   - In-mode `'` restores the last jump source when available; otherwise it falls through to the first hinted entry.
   - Invalid hint keys exit jump mode without moving, matching nearby modal jump implementations.

4. Keep async load interactions simple and deterministic.
   - A successful worker result should render normal rows unless a deliberate active jump render is still valid.
   - If the source list changes while jump mode is active, clear stale hints rather than preserving mismatched indices.
   - Preserve the existing `_syncing_options` guard around programmatic `highlighted` assignments so `OptionHighlighted`
     echoes do not create duplicate loads or cursor jumps.

5. Update user-facing hints.
   - Add `'` to the normal Logs footer hint text.
   - Show a compact jump-mode footer such as `JUMP ' first <esc> cancel` or `JUMP ' back <esc> cancel`.

6. Add focused tests.
   - Extend `tests/ace/tui/test_logs_pane.py`.
   - Cover entering jump mode and rendering hint prefixes.
   - Cover jumping directly to a later source and loading its detail.
   - Cover in-mode `'` returning to the previous jump source, and selecting the first source when no back stack exists.
   - Cover `escape` cancel behavior.
   - Include a regression assertion that cached option labels are reused for jump rendering rather than rebuilding
     source metadata on keypress, if that can be tested cleanly without overfitting internals.

## Verification

After implementation, run:

```bash
just install
just check
```

If the focused test file is useful while iterating, run:

```bash
pytest tests/ace/tui/test_logs_pane.py
```
