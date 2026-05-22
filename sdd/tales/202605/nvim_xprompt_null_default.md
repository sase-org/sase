---
create_time: 2026-05-22 14:38:26
status: done
prompt: sdd/prompts/202605/nvim_xprompt_null_default.md
---
# Fix Neovim xprompt optional null defaults

## Problem

The Telescope xprompt preview can crash with:

```text
attempt to concatenate field 'default' (a userdata value)
```

The immediate failing path is `lua/sase/xprompt.lua` in the Neovim plugin. `sase xprompt list` emits JSON `null` for
inputs whose default is explicitly `null`. Neovim's `vim.json.decode()` represents JSON `null` as the userdata sentinel
`vim.NIL`, not Lua `nil`. Existing display helpers check truthiness and then concatenate `inp.default`, so optional
`null` defaults are treated as present strings and crash.

This affects at least:

- `input_detail_label()`, used by preview input rows when the input has a description.
- `input_display_label()`, used by the fallback `vim.ui.select` display.

The Python CLI output is not the root bug: it also emits the separate `required` boolean, so clients can distinguish
required inputs from optional explicit-null inputs. The Neovim client needs to normalize decoded JSON nulls at the
display boundary.

## Scope

Modify only the workspace-matched Neovim plugin checkout:

```text
/home/bryan/.local/state/sase/workspaces/sase-org/sase-nvim/sase-nvim_10
```

No memory files should be changed.

## Implementation Plan

1. Add a small Lua helper in `lua/sase/xprompt.lua` that converts displayable scalar values to strings and treats `nil`,
   `vim.NIL`, and empty strings as absent.

2. Update input default rendering to use the helper:
   - `input_display_label()` should show `?` for optional explicit-null defaults, matching "optional but no concrete
     default".
   - `input_detail_label()` should show `(optional)` for optional explicit-null defaults rather than
     `(default: vim.NIL)` or crashing.

3. Keep existing behavior for non-empty string defaults. Be tolerant of numeric or boolean defaults if they ever arrive
   directly from JSON or tests by rendering them with `tostring()`.

4. Add regression coverage in `tests/completion_helpers.lua` for an optional input with `default = vim.NIL` and a
   description:
   - `_format_preview()` should not throw and should include an optional input detail line.
   - `_format_display()` should not throw and should show the optional marker.
   - `_preview_lines()` should still produce buffer-safe lines with no embedded newlines.

5. Run focused verification in the Neovim plugin:
   - `nvim --headless -u NONE -i NONE -n -S tests/completion_helpers.lua +qa!`
   - existing local headless Lua tests if available and relevant
   - `git diff --check`

6. Per external repo memory, run `just check` in the modified plugin repo if a justfile exists. If this plugin workspace
   still has no justfile, report that explicitly.

## Expected Outcome

Telescope and fallback xprompt browsing should tolerate optional inputs with JSON `null` defaults. Required inputs with
JSON `null` should remain required via the existing `required` flag, and multiline preview safety from the prior fix
should remain covered.
