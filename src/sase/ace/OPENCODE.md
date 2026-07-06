# Ace Subcommand Guidelines

## ChangeSpec Suffix Syntax Highlighting

**CRITICAL**: When updating styling for ChangeSpec suffix types (e.g., `killed_process`, `running_agent`, `error`), you
MUST update ALL of these files:

1. `home/dot_config/nvim/syntax/saseproject.vim` - Vim syntax highlighting (2 places: COMMITS and HOOKS sections)
2. `src/sase/ace/display.py` - CLI Rich styling (3 places: commits, hooks, comments)
3. `src/sase/ace/query/highlighting.py` - Query token styles in `QUERY_TOKEN_STYLES` dict
4. `src/sase/ace/tui/widgets/changespec_detail.py` - TUI widget Rich styling (3 places: commits, hooks, comments)

## Footer Keybinding Convention

**CRITICAL**: The TUI footer (bottom bar) shows **conditional keymaps** — bindings whose availability is determined by
the currently selected entry (ChangeSpec, Agent, etc.) or by transient app state (e.g. marks exist, completed agents
present). The implementation lives in `src/sase/ace/tui/widgets/keybinding_footer.py`.

Rules:

1. A keymap appears in the footer **if and only if** it has a condition that is sometimes true and sometimes false.
2. Global actions (quit, refresh, tab switch, fold, edit query, etc.) belong in the help modal only.

Formatting:

- Keymaps are sorted alphabetically; symbol keys (`<enter>`, `<space>`, `.`) come first.
- Named keys are rendered in lowercase angle brackets: `<enter>`, `<space>`.

## Help Popup Maintenance

**CRITICAL**: Whenever you modify a `sase ace` option (add, remove, or change behavior), you MUST update the `?` (help)
popup content to keep the documentation in sync with the actual functionality.

## Help Modal Box Formatting

**CRITICAL**: The help modal boxes must maintain consistent 57-character width. When modifying `help_modal.py`:

1. All box sections use `_BOX_WIDTH = 57` and `_CONTENT_WIDTH = 50`
2. Keybinding descriptions: max 32 chars (truncate with "..." if longer)
3. Saved query display: max 36 chars when active indicator shown, 45 chars otherwise
