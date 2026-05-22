---
create_time: 2026-05-22 14:22:36
status: done
prompt: sdd/prompts/202605/nvim_telescope_preview_newlines.md
---
# Fix Neovim Telescope xprompt preview newline crash

## Context

The Neovim error occurs in `lua/telescope/_extensions/sase.lua` when the Telescope previewer calls
`vim.api.nvim_buf_set_lines()` with the result of `xprompt._preview_lines(item)`.

The latest `sase-nvim` commit changed the preview path from splitting only `item.preview` into lines to building richer
preview content from xprompt and input descriptions. That helper currently appends `item.description` and
`inp.description` as single list entries. If `sase xprompt list` returns a multiline description, any list entry
containing an embedded newline is passed to `nvim_buf_set_lines()`, which raises:

`'replacement string' item contains newlines`

## Plan

1. Reproduce the invariant locally at helper level.
   - Add or extend Lua tests with an xprompt item whose main description, input description, and preview contain
     embedded newlines.
   - Assert that `_preview_lines()` returns a list where no element contains `\n` or `\r`.
   - Keep existing output expectations intact for one-line descriptions.

2. Fix preview line construction in `lua/sase/xprompt.lua`.
   - Introduce a small helper that appends arbitrary text as buffer-safe lines by splitting on newline boundaries.
   - Use it for xprompt descriptions, input description bullet text, and preview body text.
   - Preserve headings and blank-line separators so the Telescope preview remains readable.

3. Audit adjacent display paths touched by the same commit.
   - Check whether Telescope display and `vim.ui.select` fallback can receive embedded newlines in fields that are
     expected to be one-line labels.
   - If necessary, normalize row/search text separately from preview text so picker rows stay stable while preview text
     keeps multiline formatting.

4. Verify in the `sase-nvim` workspace.
   - Run the existing Lua helper tests with headless Neovim.
   - Run any repository check command available in the plugin workspace. If `just check` is unavailable in this repo,
     record that and run the concrete headless test commands instead.

5. Report the root cause and the exact files changed.
   - Mention that the recent commit introduced the bug by adding unsplit description text to the preview line array.
   - Include verification results and any remaining manual Neovim smoke check worth doing.
