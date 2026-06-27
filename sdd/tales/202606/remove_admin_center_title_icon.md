---
create_time: 2026-06-27 07:47:03
status: done
prompt: sdd/prompts/202606/remove_admin_center_title_icon.md
---
# Plan: Remove the SASE Admin Center title icon

## Goal

Remove the small icon currently rendered before the `SASE Admin Center` title in the Admin Center modal header, while
preserving the rest of the header treatment: centered title, aurora gradient, matching underline, tab strip, active-tab
caption, and existing keyboard/mouse behavior.

## Current Shape

The Admin Center is implemented by `ConfigCenterModal` in `src/sase/ace/tui/modals/config_center_modal.py`.

The title is currently assembled from:

- `_TITLE_ICON = "⎈"`
- `_TITLE_LABEL = "SASE Admin Center"`
- `_TITLE_TEXT = f"{_TITLE_ICON} {_TITLE_LABEL}"`
- `_TITLE_UNDERLINE = _TITLE_RULE_CHAR * len(_TITLE_TEXT)`

The stylesheet in `src/sase/ace/tui/styles.tcss` only controls title layout and centering. It does not inject or size
the icon separately, so this should be a rendering-data change rather than a CSS change.

## Implementation Plan

1. Update `src/sase/ace/tui/modals/config_center_modal.py` so `_TITLE_TEXT` is exactly `_TITLE_LABEL`. Remove
   `_TITLE_ICON` if it becomes unused.

2. Keep `_TITLE_UNDERLINE` derived from `len(_TITLE_TEXT)` so the underline automatically shrinks to match the iconless
   title. This avoids leaving a visually wider rule after removing the two-character icon prefix.

3. Leave `_gradient_text()`, `_TITLE_GRADIENT`, the title widgets, and `styles.tcss` unchanged. The title should remain
   centered and gradient-styled; only the leading glyph and its trailing space should disappear.

4. Add a focused regression test in `tests/ace/tui/test_config_center_tabs.py` for the title constants/rendered content:
   the plain title should be `SASE Admin Center`, should not start with the old icon, and the underline length should
   match the title text length.

5. Review the Admin Center PNG visual snapshot coverage. Existing snapshots across Config, Logs, Projects, Tasks,
   Updates, and XPrompts all include the shared header, so the visual delta should be intentional and limited to the
   title/underline width. Update visual goldens only if the implementation is otherwise correct and the snapshot diff
   shows only that expected header change.

## Verification

Before finalizing implementation:

1. Run `just install` first if this workspace has not already been prepared.
2. Run the focused Admin Center tab/title test, for example the `tests/ace/tui/test_config_center_tabs.py` module.
3. Run the relevant Admin Center visual snapshot suite, or the dedicated `just test-visual` suite if snapshot updates
   are needed.
4. Run `just check` after file changes, per repo instructions.

## Scope Notes

This is presentation-only Textual state, so it stays in the Python TUI layer. It does not require Rust core changes,
configuration changes, keymap changes, or documentation changes.
