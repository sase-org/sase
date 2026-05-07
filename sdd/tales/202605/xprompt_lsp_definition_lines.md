---
create_time: 2026-05-07 16:08:51
status: wip
prompt: sdd/prompts/202605/xprompt_lsp_definition_lines.md
---
# Plan: Precise LSP Definition Lines for Config-Backed Xprompts

## Goal

Jump-to-definition for xprompt references should land on the line where the referenced xprompt or workflow is defined,
not merely at the top of `sase.yml`, `default_config.yml`, or plugin config files.

## Current Behavior

The Python repo only launches the LSP and passes catalog path environment variables. The actual definition response
lives in `../sase-core`:

- `sase_xprompt_lsp::server::definition_for_text()` asks `sase_core::editor_definition_at_position()`.
- `editor::definition::definition_at_position()` resolves the referenced catalog entry and returns its
  `definition_path`, with `range: None`.
- The LSP converts `None` to `zero_range()`, so Neovim opens the correct file at line 1.
- The Rust catalog loader already knows whether an entry came from an xprompt file, workflow file, `sase.yml`,
  `default_config.yml`, plugin config, or a config overlay, but it only exposes the path.

## Design

Add optional source range metadata to the editor xprompt catalog wire model and thread it through to definition results:

1. Extend the catalog/editor wire structs with an optional `definition_range`.
   - Keep it optional with serde defaults so older helper responses remain compatible.
   - Reuse existing editor position/range shapes where possible.

2. Populate `definition_range` in the Rust catalog loader.
   - File-backed `.md` xprompts and standalone `.yml` workflow files may keep `None`, preserving current line-1 behavior
     for files whose whole file is the definition.
   - Config-backed xprompts under `xprompts:` should point at the specific child key line.
   - Config-backed workflows under `workflows:` should do the same, since they share the same jump-to-definition path.
   - Handle default config, user config, config overlays, local `sase.yml`, plugin `default_config.yml`, and known
     project `sase.yml`.

3. Implement a small line-oriented YAML key locator for this narrow use case.
   - Find the top-level `xprompts:` or `workflows:` mapping.
   - Within that mapping, find the immediate child key matching the catalog entry name.
   - Respect indentation enough to avoid matching nested keys.
   - Support common quoted and unquoted YAML keys.
   - Return a zero-based LSP/editor range spanning the key token on that line.
   - If location cannot be found, leave `definition_range` as `None` so the current path-only behavior remains the
     fallback.

4. Update `editor::definition::definition_at_position()` to return the catalog entry's `definition_range` when present.

5. Add focused tests in `../sase-core`.
   - Catalog tests for `default_config.yml`, local `sase.yml`, plugin config, and project-local `sase.yml` entries
     assert the computed line.
   - Editor definition tests assert the returned target range is preserved.
   - LSP server tests assert `textDocument/definition` returns a nonzero range when the catalog includes one.

6. Verification.
   - Run the relevant `cargo test` packages in `../sase-core`.
   - Because this work changes the sibling Rust core rather than the Python repo, run targeted Python tests only if the
     Python wire/launcher surface changes. Otherwise no Python code needs edits.

## Risks and Boundaries

This should stay in the Rust core because editor definition behavior is shared backend behavior. The line locator should
remain conservative: exact line when confidently found, existing line-1 fallback otherwise. No Neovim plugin change
should be required because LSP `Location.range` already carries the target line.
