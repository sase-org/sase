---
create_time: 2026-05-28 10:21:45
status: done
prompt: sdd/prompts/202605/nvim_xprompt_frontmatter_hover.md
---
# Plan: xprompt Markdown frontmatter hover

## Goal

Make normal Neovim `K` hover show useful documentation for xprompt Markdown frontmatter fields, especially `xprompts`,
in files where the SASE xprompt LSP is attached.

## Current behavior

- `sase-nvim` attaches `sase-xprompt-lsp` to Markdown buffers under `xprompts/` and `.xprompts/`, plus prompt temp
  files.
- The LSP already advertises hover support, so Neovim `K` can work without a new keymap when the server returns hover
  content.
- `sase-core` hover currently handles xprompt references, slash skills, xprompt call arguments, and directives.
- `sase-core` frontmatter support already parses Markdown YAML frontmatter and validates known top-level fields,
  including `xprompts`, but that index is private to diagnostics and is not used by hover.

## Implementation

1. Add a frontmatter hover API in `crates/sase_core/src/editor/frontmatter.rs`. It should:
   - Extract Markdown frontmatter only when the document starts with a fenced `---` YAML block.
   - Use the existing source index to locate top-level field keys by byte range.
   - Return a `HoverPayload` with the key range and Markdown documentation when the cursor is over a known field key.
   - Start with top-level fields already accepted by diagnostics: `name`, `input`, `tags`, `description`, `skill`,
     `snippet`, `keywords`, and `xprompts`.

2. Define field documentation close to the frontmatter validation rules. The `xprompts` copy should explicitly say that
   the field defines local xprompts available only within the current file. Keep the wording concise enough for an
   editor hover.

3. Wire the new API into `crates/sase_core/src/editor/hover.rs` before generic token hover. This ensures field-key hover
   wins over unrelated token parsing and keeps Neovim behavior unchanged: `K` calls standard LSP hover.

4. Add focused Rust tests:
   - Core hover test for `xprompts:` in Markdown frontmatter that verifies a hover exists, the range covers the field
     key, and the markdown mentions local/current-file xprompts.
   - A negative/core guard that body text or non-field positions do not produce frontmatter field hover.
   - LSP server hover test proving `hover_for_text` exposes the frontmatter hover through the existing server conversion
     path.

5. Verify with targeted tests first, then broader checks as needed:
   - `cargo test -p sase_core editor::hover`
   - `cargo test -p sase_xprompt_lsp exposes_hover_diagnostics_code_actions_and_definition`
   - If the edits are broader than expected, run the relevant full crate tests.

## Scope notes

- No Neovim Lua keymap change should be necessary unless testing shows the LSP client is not attached for xprompt
  Markdown files.
- This should live in `sase-core` because hover semantics are shared editor domain behavior, while `sase-nvim` is only
  the frontend invoking LSP hover.
- YAML schema hover from `yamlls` is not the right primary mechanism here: this feature should work through the SASE
  xprompt LSP wherever that LSP is used.
