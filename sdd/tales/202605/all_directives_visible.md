---
create_time: 2026-05-09 22:43:16
status: wip
prompt: sdd/prompts/202605/all_directives_visible.md
---
# Make directive completion show every directive

## Problem

When the prompt cursor is to the right of a `%` token and the user presses `<ctrl+t>`, the ace prompt bar opens the
directive completion panel. The current screenshot shows only eight directives:

- `%alt`
- `%approve`
- `%edit`
- `%epic`
- `%hide`
- `%model`
- `%name`
- `%plan`

The directive catalog currently exposes eleven user-facing directives:

- `%alt`
- `%approve`
- `%edit`
- `%epic`
- `%hide`
- `%model`
- `%name`
- `%plan`
- `%repeat`
- `%tag`
- `%wait`

The missing directives are therefore not absent from the candidate builder; they are being hidden by completion-panel
presentation limits.

## Current Flow

- `PromptTextArea._try_file_completion_tab()` detects directive context through
  `extract_directive_token_around_cursor()`.
- `build_directive_completion_candidates("%")` returns all user-facing directive candidates from
  `src/sase/ace/tui/widgets/directive_completion.py`.
- `FileCompletionMixin._update_file_completion_panel()` applies the shared `MAX_VISIBLE` scrolling logic from file/path
  completions.
- `PromptInputBar.show_file_completions()` slices the visible rows using `MAX_VISIBLE`, then renders the same completion
  widget for file, xprompt, directive, history, and xprompt-argument completions.
- The stylesheet caps `#prompt-completion` with `max-height: 10`, so even a ten-row rendered completion panel can be
  visually clipped once borders/padding/margins are included.

## Proposed Design

Treat directive completion as a small, finite catalog rather than as an unbounded file/path completion list.

1. Keep the directive candidate source as-is.
   - `build_directive_completion_candidates("%")` already returns the expected directives and metadata.
   - This avoids duplicating directive definitions or adding a second source of truth.

2. Give directive completion its own visible-row limit.
   - Add a small helper/constant near the completion rendering code, such as `DIRECTIVE_MAX_VISIBLE`, computed to be at
     least the current number of directive candidates.
   - In `PromptInputBar.show_file_completions()`, use this directive-specific limit when
     `completion_kind == "directive"` instead of the shared file `MAX_VISIBLE`.
   - In `FileCompletionMixin._update_file_completion_panel()`, use the same per-kind visible limit for scroll offset
     math so keyboard navigation remains consistent.

3. Raise or remove the CSS cap that clips the completion widget.
   - The current `max-height: 10` is lower than what the prompt bar may need for all directive rows plus border/padding.
   - Prefer a small named constant in Python for completion line count and a matching CSS cap high enough for the known
     directive catalog, while still keeping the prompt bar bounded by `PromptInputBar._update_height()` and the screen
     height.
   - Avoid making path/history/xprompt completion panels huge; only directive completion needs to guarantee all rows.

4. Preserve existing behavior for other completion kinds.
   - File, file-history, xprompt, and xprompt-argument completions should continue to use scrolling and the existing
     shared `MAX_VISIBLE` behavior.
   - Acceptance, arrow navigation, partial filtering, alias matching, and shared-prefix completion should remain
     unchanged.

## Tests

Add targeted tests in `tests/ace/tui/widgets/test_directive_completion.py`:

1. A pure builder assertion that `%` returns every user-facing directive, including `%repeat`, `%tag`, and `%wait`.
2. A Textual prompt-bar test that pressing `<ctrl+t>` at `%` renders every returned directive in the panel text.
3. A regression assertion that the rendered directive panel does not include a `more` overflow indicator for the bare
   `%` case.

If CSS changes are hard to assert directly in the lightweight widget test, assert the Python-side line count/visible row
behavior and rely on existing TUI style loading plus the focused manual screenshot for the final visual check.

## Verification

Run focused tests first:

```bash
just install
uv run pytest tests/ace/tui/widgets/test_directive_completion.py
```

Because this repo requires it after file changes, finish with:

```bash
just check
```

## Risk

The main risk is accidentally increasing the completion panel height for unbounded completion types, which would crowd
the TUI. Keeping the larger no-scroll behavior scoped to `completion_kind == "directive"` minimizes that risk.
