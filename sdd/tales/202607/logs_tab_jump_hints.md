---
create_time: 2026-07-08 03:01:21
status: wip
prompt: sdd/prompts/202607/logs_tab_jump_hints.md
---
# Plan: Logs Tab Apostrophe Jump Hints

## Goal

Add or verify support for the existing apostrophe jump-to-entry interaction in the SASE Admin Center Logs tab, so a user
can press `'`, see one-key hints beside log-source sidebar entries, press a hint to move to that source, and press `'`
again in jump mode to return to the previous source or fall back to the first source.

## Current Architecture Notes

- The global/app-level jump action is already named `jump_to_entry`, with the default binding configured as
  `apostrophe`.
- The Admin Center is hosted by `ConfigCenterModal` and uses screen-level digit bindings for tab switching. Any logs-tab
  jump mode must consume hint keys before those screen bindings accidentally switch tabs.
- The Logs tab UI lives in `src/sase/ace/tui/modals/logs_pane.py` as a two-panel layout: a source sidebar and a detail
  pane.
- The shared hint alphabet and shifted-key normalization live in `src/sase/ace/tui/actions/navigation/jump_hints.py`;
  Logs should reuse this helper so hint ordering and uppercase dispatch match Agents, ChangeSpecs, and other modals.
- Log detail loading is intentionally off-thread. Jump handling should only update focus/selection/hint chrome on the
  event loop and use the existing load path for detail refreshes.

## Implementation Plan

1. Audit the current LogsPane implementation before changing code.
   - Confirm whether `LogsPane` already binds `apostrophe` to `jump_to_entry`.
   - Confirm whether it stores hint maps, jump-mode state, and a bounded back stack for source selections.
   - Confirm whether `on_key` consumes hint keys while jump mode is active, especially digit hints that overlap with
     Admin Center tab hotkeys.

2. Fill any missing behavior in `LogsPane` using the existing local pane style.
   - Build hint mappings with `build_jump_hint_maps(range(len(source_options)))`.
   - Render hints directly into cached source labels, not by rereading log files or rebuilding source metadata.
   - Add an active jump-mode footer hint such as `JUMP ' first/back  <esc> cancel`.
   - On a valid hint, clear hints, highlight the target source, push the previous source onto a bounded back stack, and
     reuse `_start_load(..., reset_scroll=True)` for detail refresh.
   - On `'` while in jump mode, pop a valid prior source from the back stack; if no valid prior source exists, dispatch
     the first source hint.
   - On `escape`, exit jump mode without closing the Admin Center.
   - On invalid keys, cancel jump mode without changing the selected source.

3. Preserve Admin Center behavior outside jump mode.
   - Keep `1`-`6` as tab hotkeys when jump mode is inactive.
   - Keep `[` and `]` as Admin Center tab navigation.
   - Keep `j/k`, arrows, `ctrl+n/p`, `r`, `g/G`, and `ctrl+d/u` behavior unchanged.
   - Do not add a new default-config action unless the implementation introduces a new configurable keymap. Reusing
     `jump_to_entry` should not require a `src/sase/default_config.yml` change.

4. Keep performance characteristics aligned with TUI guidance.
   - Do no synchronous log reads or metadata scans from key handlers.
   - Reuse cached option labels when entering or exiting jump mode.
   - Continue using the existing threaded load worker for selected log detail.
   - Maintain the existing `_syncing_options` guard around programmatic `OptionList` updates.

5. Add or adjust tests around the complete user flow.
   - Pane-level: pressing `'` shows `[1]`, `[2]`, etc. beside sidebar entries.
   - Pane-level: pressing a numeric hint selects the matching source and loads its detail.
   - Pane-level: pressing `'` in jump mode returns to the previous source, and falls back to the first source with no
     history.
   - Modal-level: digit hints are consumed by the LogsPane while jump mode is active and do not switch Admin Center
     tabs.
   - Modal-level: `escape` cancels jump mode while keeping the Admin Center open.
   - Regression: entering jump mode reuses cached source labels rather than recomputing source metadata.

6. Verification
   - Run focused tests for the Logs tab and Admin Center tab hotkeys.
   - If code changes are made in this repo, run `just check` after `just install` per project instructions.

## Baseline Finding

Initial inspection and focused test execution indicate the current workspace already has a `LogsPane` implementation for
this interaction, including apostrophe binding, source-row hints, jump/back behavior, escape cancellation, and tests for
the main pane flow. If that remains true during implementation, the correct change may be limited to adding any missing
modal-level regression coverage or making no code changes after documenting that the requested behavior is already
present.
