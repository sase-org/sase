---
create_time: 2026-05-07 15:24:58
status: done
prompt: sdd/prompts/202605/xprompt_lsp_definition_e2e_fix.md
---
# Plan: Fix XPrompt LSP Jump To Definition End To End

## Context

Jump-to-definition for xprompt references has already been partially implemented in the Rust LSP stack. The current code
advertises `textDocument/definition`, threads a `definition_path` field through the catalog wire model, and resolves
that field through `editor_definition_at_position()`.

The user-visible failure is still real: Neovim can appear to open the right file while the buffer is empty, and
definition must work for all xprompt source classes, including built-in xprompts and plugin-defined xprompts.

The likely remaining gap is not the basic LSP method. It is the real catalog and client launch contract:

- `source_path_display` is display-only and must never be used for navigation.
- `definition_path` must be present and absolute for real local files in both Rust-loaded catalogs and helper-loaded
  catalogs.
- Normal Neovim startup prefers `sase lsp`, but users can also hit the direct `sase-xprompt-lsp` fallback or override
  command. Those paths must not lose plugin definitions.
- Existing tests cover many pure functions, but they do not yet prove that a real Neovim LSP definition request opens a
  populated file buffer.

## Goals

- Make `textDocument/definition` return a valid `file://` URI backed by an existing file for:
  - project/local xprompts,
  - built-in package xprompts,
  - default built-in xprompts,
  - config-backed xprompts whose source is a real config file,
  - plugin package xprompts and plugin default-config workflows when plugin resources are real files,
  - slash skills such as `/sase_plan`,
  - namespaced shorthand such as `#gh__review`.
- Preserve conservative behavior for synthetic or unsafe sources: no definition instead of guessed paths.
- Add an end-to-end proof using the real server protocol and headless Neovim, not only unit tests.

## Implementation Plan

1. Reproduce the failure through real request paths before editing behavior.
   - Start from focused unit tests already in `../sase-core`.
   - Run a JSON-RPC definition request against the real `sase lsp` wrapper for built-in and plugin entries.
   - Run headless Neovim with the local `sase-nvim` plugin, attach the xprompt LSP to a temp prompt file, invoke
     `vim.lsp.buf.definition()`, and assert the resulting buffer path and content.

2. Fix catalog source resolution where real source paths are missing.
   - Audit both catalog loaders:
     - Rust: `../sase-core/crates/sase_core/src/xprompt_catalog.rs`.
     - Python helper: `src/sase/xprompt/_catalog_sources.py`.
   - Ensure plugin pseudo-sources like `plugin:<module>/<file>` resolve back to concrete files via plugin resource
     discovery when possible.
   - Ensure plugin config pseudo-sources like `plugin_config:<module>` resolve to plugin `default_config.yml` when
     possible.
   - Keep all emitted `definition_path` values absolute, canonical, and file-backed.

3. Fix LSP conversion only if the reproducer shows bad URI or buffer behavior.
   - Keep returning standard `Location` with `file://` URI and zero range.
   - Validate the path exists before converting it to a URI.
   - Do not add Neovim-specific path parsing in Lua.

4. Strengthen automated tests.
   - Python tests: add plugin `definition_path` coverage using fake `sase_xprompts` and `sase_config` modules.
   - Rust tests: keep/extend plugin, built-in, slash skill, and outside-workspace definition coverage.
   - Neovim tests: add a headless smoke test that performs an actual LSP definition request and asserts the opened
     buffer is non-empty and points to the expected file.

5. Verify across touched repos.
   - In `sase_100`: run `just install` first if needed, targeted Python tests, then `just check`.
   - In `../sase-core`: run focused Rust tests, then `cargo fmt --all -- --check`,
     `cargo clippy --workspace --all-targets -- -D warnings`, and `cargo test --workspace`.
   - In `../sase-nvim`: run the existing Lua test command plus the new headless Neovim definition smoke. If files are
     changed there, run its `just check` if available.

## Acceptance Criteria

- A real `sase lsp` JSON-RPC request for `#sase_plan`, a built-in non-skill xprompt, and a plugin xprompt returns a
  `file://` URI whose path exists and has content.
- A real headless Neovim session using `../sase-nvim` can invoke standard go-to-definition on those references and land
  in a non-empty buffer for the expected local file.
- Direct `sase-xprompt-lsp` fallback either resolves plugin definitions through the helper/catalog path or degrades only
  when plugin resources are unavailable as real local files.
- Existing completion, hover, diagnostics, and code-action behavior remain unchanged.
