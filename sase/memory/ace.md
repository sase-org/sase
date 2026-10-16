---
type: reference
parent: AGENTS.md
description: Read before changing anything under `src/sase/ace/`.
---

# Ace Subcommand Guidelines

TUI screenshot, visual snapshot, and performance rules live in [[tui.md]].

## Patch Suffix Syntax Highlighting

When updating styling for Patch suffix types (for example `killed_process`,
`running_agent`, `error`), update all of these:

1. The `sase-nvim` linked repo's `syntax/sase_project_spec.vim` — Vim syntax for suffix
   markers and highlight groups. Open it with `sase repo open sase-nvim` before editing.
2. `src/sase/ace/display.py` — CLI Rich styling (stitches, hooks, comments, mentors).
3. `src/sase/ace/query/highlighting.py` — query token styles in `QUERY_TOKEN_STYLES`.
4. `src/sase/ace/tui/widgets/suffix_formatting.py` — TUI `SUFFIX_STYLES` used by the
   stitches, hooks, comments, and mentors builders.

## Footer Keybinding Convention

The TUI footer (bottom bar) shows **conditional keymaps** — bindings whose availability
is determined by the currently selected entry (Patch, Agent, etc.) or by transient app
state (for example marks exist, completed agents present). The implementation lives in
`src/sase/ace/tui/widgets/keybinding_footer.py`.

Rules:

1. A keymap appears in the footer **if and only if** it has a condition that is
   sometimes true and sometimes false.
2. Global actions (quit, refresh, tab switch, fold, edit query, etc.) belong in the help
   modal only.

Formatting:

- Keymaps are sorted alphabetically; symbol keys (`<enter>`, `<space>`, `.`) come first.
- Named keys are rendered in lowercase angle brackets: `<enter>`, `<space>`.

## Help Popup Maintenance

Whenever you modify a `sase tui` option (add, remove, or change behavior), update the
`?` (help) popup content so the documentation stays in sync with the actual
functionality.

## Help Modal Box Formatting

Help modal boxes keep a consistent 57-character width. The constants live in
`src/sase/ace/tui/modals/help_modal/binding_common.py`:

- `BOX_WIDTH = 57` and `CONTENT_WIDTH = 50`
- Keybinding descriptions truncate to `CONTENT_WIDTH - 16 - 2` (32 chars) with `...`
- Saved-query display width is `CONTENT_WIDTH` minus the `[prefix+slot]` badge and, when
  the query is active, the 9-character ` ● active` indicator
