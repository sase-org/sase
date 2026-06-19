---
create_time: 2026-06-19 13:57:27
status: wip
prompt: sdd/prompts/202606/fix_vcs_project_lsp_enter.md
---
# Plan: Fix `+` Project Completion Blank Line On Enter

## Current Diagnosis

The `+` VCS-project expansion logic itself is behaving correctly in the shared contract:

- Python/TUI `apply_vcs_project_selection("+sa", (0, 3), "#gh:sase")` expects `#gh:sase `.
- Rust core has the same golden vector and computes the same canonical text.
- The Rust edit builder should merge a start-of-document `+query` replacement into one primary LSP `textEdit` replacing
  the trigger with `#gh:sase `, with no `additionalTextEdits`.

The exposed gap is the Neovim acceptance path. The current `sase-nvim` smoke test requests LSP completion and applies
`textEdit`/`additionalTextEdits` manually with `vim.lsp.util.apply_text_edits`; it does not simulate accepting the popup
with `<Enter>`. `sase-nvim` enables Neovim native `vim.lsp.completion`, but does not install any `<CR>` handling. With
native insert completion, `<CR>` can both accept the selected completion item and perform its normal newline insertion.
At the start of a line, that extra newline lands before the accepted `#gh:sase ` text, producing:

```text

#gh:sase
```

instead of:

```text
#gh:sase
```

## Implementation Plan

1. Add a focused Rust LSP regression for the queried start-token shape.
   - In `sase-core`, extend the `vcs_project` LSP tests so `+s` at line 0, character 2 returns a single primary
     `textEdit` replacing `[0:0, 0:2]` with `#gh:sase ` and no `additionalTextEdits`.
   - This locks down the server side and proves the fix belongs in the client accept path if the item shape is already
     correct.

2. Add a real Neovim acceptance regression.
   - Extend or add a `sase-nvim` headless test that starts the real xprompt LSP against a temporary prompt buffer, types
     `+s`, waits for the completion menu, accepts with `<Enter>`, and asserts the buffer is exactly `#gh:sase `.
   - Keep the existing manual-edit smoke test coverage, but add this interactive path because that is where the blank
     line is introduced.

3. Fix `sase-nvim` native completion Enter handling.
   - In `lua/sase/lsp.lua`, when native `vim.lsp.completion` is enabled for the SASE xprompt LSP buffer, install a
     buffer-local insert-mode `<CR>` mapping that returns `<C-y>` while the popup menu is visible and falls back to
     normal `<CR>` otherwise.
   - Keep the mapping limited to buffers where `sase-xprompt-lsp` native completion is attached, so normal editing and
     users of `nvim-cmp` remain outside this path.
   - Avoid clobbering an existing buffer-local `<CR>` mapping if one is already present; in that case, leave the user's
     mapping in charge.

4. Update plugin docs if needed.
   - Adjust the `sase-nvim` README language that currently says no extra Lua configuration is required, noting that the
     plugin handles native completion `<Enter>` confirmation for SASE prompt buffers.

5. Verify with focused checks.
   - In `sase-core`: run the focused `vcs_project` Rust tests for `sase_core` and `sase_xprompt_lsp`.
   - In `sase-nvim`: run the Lua/headless LSP config tests and the `lsp_vcs_project_smoke` test.
   - If a source change is required in the main `sase` repo after this plan, run its required `just check`; otherwise
     keep verification scoped to the repos that changed.

## Expected Outcome

Typing `+s<Enter>` at the start of a SASE prompt buffer accepts the `sase` project completion as `#gh:sase ` with no
leading blank line, while trailing `+` expansion and existing VCS-tag replacement continue to behave as they do today.
