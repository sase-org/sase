---
create_time: 2026-05-07 12:52:11
status: done
prompt: sdd/prompts/202605/xprompt_lsp_jump_definition.md
bead_id: sase-2b
tier: epic
---
# Plan: XPrompt LSP Jump To Definition

## Context

SASE recently gained an xprompt language server. The user-facing goal for this follow-up is narrow but important: when
the cursor is on an xprompt reference such as `#foo`, `#!bd/work_phase_bead`, `#gh__review`, or `/sase_plan`, an editor
should be able to use standard LSP jump-to-definition and land on the file that defines that xprompt.

There is already some jump-to-definition scaffolding in `../sase-core`:

- `crates/sase_xprompt_lsp/src/server.rs` advertises `definition_provider`.
- `XpromptLspServer::definition_for_text()` extracts a token, finds a catalog entry, and returns an LSP `Location`.
- `safe_source_uri()` currently derives a URI from `XpromptAssistEntry.source_path_display`.

That implementation is a useful sketch, but it should not be treated as complete. `source_path_display` is intentionally
a display string, not an editor navigation contract. It can be relative to the current workspace, relative to the SASE
package directory, `~/.config/sase/...`, `config`, `plugin:...`, or absent. The current containment check also rejects
valid global/user/package xprompt definitions outside the editor workspace. Jump-to-definition should be backed by
structured source metadata, not by parsing a human-facing label.

## Product Scope

Supported jump targets for the MVP:

- Disk-backed project xprompts from `.xprompts/`, `xprompts/`, and project-specific xprompt directories.
- Disk-backed user/global xprompts under `~/.config/sase/xprompts/`, `~/xprompts`, and `~/.xprompts`.
- Built-in/package xprompts in `src/sase/xprompts/` and `src/sase/default_xprompts/`.
- Config-backed xprompts in SASE config files when the loader knows the config file path.
- Memory-backed xprompts when they originate from a real memory file.
- Slash-skill references such as `/sase_plan`, using the same catalog entry as the equivalent xprompt.
- Namespaced shorthand normalization already used by hover/completion, especially `#foo__bar` -> `foo/bar`.

Unsupported or best-effort targets:

- Plugin pseudo-sources such as `plugin:module/name` should return no definition unless the catalog can supply a real
  local path for that plugin xprompt.
- Entries with no source metadata should return `None` rather than fabricating a URI.
- The MVP only needs file-level navigation. A later refinement can jump to the exact YAML key or frontmatter/body line.

## Cross-Repo Boundaries

Primary implementation belongs in `../sase-core` because editor/backend behavior should be shared across clients.

The Python repo `sase_102` remains authoritative for the helper-backed catalog path used by installed environments. It
must expose the same structured definition target as the Rust catalog loader, without leaking unsafe absolute paths
through mobile/public surfaces unintentionally.

The Neovim repo `../sase-nvim` should stay thin. Standard LSP clients already know how to call
`textDocument/definition`; Neovim work should be limited to smoke coverage, docs, and optional convenience mappings only
if the existing setup does not make definition available naturally.

## Phase 1: Define A Real XPrompt Source Target Contract

**Owner:** catalog/wire agent.

**Repos:** `sase_102` and `../sase-core`.

**Goal:** add structured, machine-readable source target metadata to xprompt catalog entries so editor navigation does
not depend on `source_path_display`.

**Primary files:**

- `sase_102/src/sase/xprompt/_catalog_models.py`
- `sase_102/src/sase/xprompt/_catalog_structured.py`
- `sase_102/src/sase/xprompt/_catalog_sources.py`
- `sase_102/src/sase/integrations/_mobile_helper_catalog.py`
- `sase_102/tests/test_xprompt_catalog.py`
- `../sase-core/crates/sase_core/src/host_bridge.rs`
- `../sase-core/crates/sase_core/src/editor/wire.rs`
- `../sase-core/crates/sase_core/src/editor/completion.rs`
- `../sase-core/crates/sase_core/src/xprompt_catalog.rs`
- `../sase-core/crates/sase_core/tests/python_wire_parity.rs`

**Design:**

- Add an optional editor navigation field to catalog entries, for example `definition_path`.
- The field should contain a real local filesystem path when there is a real local file to open.
- Prefer absolute normalized paths for the LSP/editor contract. Keep `source_path_display` for UI text.
- Keep the field optional and backward-compatible in Rust deserialization so older Python helpers still work.
- Decide explicitly whether the existing mobile HTTP gateway may return this field. If exposing absolute paths over the
  gateway is too broad, add an editor/helper-only projection while preserving the mobile-safe response shape.
- Preserve `source_path_display` behavior and existing catalog JSON fields.

**Acceptance criteria:**

- Python structured catalog entries include `definition_path` for project, user/global, package, default, config-file,
  and memory-file backed xprompts when the source is a real file.
- Plugin/config pseudo-sources without a real file keep `definition_path = None`.
- Rust helper wire structs accept both old JSON without the field and new JSON with the field.
- Rust catalog loader populates the same field for Rust-loaded entries.
- Tests cover at least one workspace-relative xprompt, one package/default xprompt, one `~/.config/sase` xprompt, and
  one pseudo-source that intentionally has no definition path.

**Verification:**

- In `sase_102`: `just install`, targeted Python catalog/helper tests, then `just check`.
- In `../sase-core`: targeted Rust catalog/wire tests, then full `cargo fmt --all -- --check`,
  `cargo clippy --workspace --all-targets -- -D warnings`, and `cargo test --workspace`.

## Phase 2: Move Definition Resolution Into Core Editor Logic

**Owner:** core editor analyzer agent.

**Repo:** `../sase-core`.

**Goal:** expose a pure Rust definition resolver in `sase_core::editor`, so LSP conversion is thin and other editor
frontends can reuse the same behavior.

**Primary files:**

- `crates/sase_core/src/editor/mod.rs`
- new or existing `crates/sase_core/src/editor/definition.rs`
- `crates/sase_core/src/editor/token.rs`
- `crates/sase_core/src/editor/wire.rs`
- tests beside the editor modules

**Design:**

- Add a small core return type, for example `DefinitionTarget { path: PathBuf, range: Option<EditorRange> }`.
- Resolve tokens using the same token extraction and normalization as hover/completion: `#name`, `#!name`, `#ns__name`,
  and `/skill`.
- Resolve only exact catalog matches. Unknown xprompts return `None`.
- Use the new `definition_path` field, not `source_path_display`.
- Validate that the path is a local file before returning a target.
- Avoid workspace-root containment as a blanket rule; global config and package xprompts are valid definitions.
- Keep path validation conservative: reject empty strings, URI-like strings, newlines, and non-file paths.

**Acceptance criteria:**

- Pure editor tests cover inline xprompt, standalone xprompt, namespaced double-underscore shorthand, slash skill,
  missing catalog entry, missing source target, nonexistent file, and global/package files outside the workspace.
- Existing hover/completion behavior is unchanged.
- `sase_core` re-exports the definition API consistently with the existing editor APIs.

**Verification:**

- `cargo fmt --all -- --check`
- `cargo clippy --workspace --all-targets -- -D warnings`
- `cargo test -p sase_core editor::definition`
- Full `cargo test --workspace` if the phase touches shared wire/catalog code.

## Phase 3: Wire Standard LSP `textDocument/definition`

**Owner:** LSP protocol agent.

**Repo:** `../sase-core`.

**Goal:** make the LSP server return robust `Location` responses through the standard definition request.

**Primary files:**

- `crates/sase_xprompt_lsp/src/server.rs`
- `crates/sase_xprompt_lsp/src/lsp_convert.rs`
- `crates/sase_xprompt_lsp/tests/jsonrpc_stdio.rs`

**Design:**

- Replace ad hoc `safe_source_uri(source_path_display, root_dir)` resolution with the Phase 2 core definition API.
- Keep `definition_provider: true`.
- Return `None` for unsupported/pseudo-source entries.
- Return a `Location` with a `file://` URI and range `(0, 0)..(0, 0)` for the MVP.
- Keep the existing "Open xprompt source" code action aligned with the same resolver or remove divergent behavior.
- Ensure catalog refresh/error behavior matches completion: missing/old helper data should degrade to no definition, not
  crash or warn repeatedly.

**Acceptance criteria:**

- Unit tests prove `definition_for_text()` works for a temp xprompt file outside the workspace root.
- Tests prove no definition is returned for `plugin:...`/missing source entries.
- Existing hover, diagnostics, code-action, and completion tests still pass.
- A JSON-RPC integration test opens a document containing `#foo` and receives a valid `textDocument/definition` result.

**Verification:**

- `cargo test -p sase_xprompt_lsp`
- Full `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`, and
  `cargo test --workspace`.

## Phase 4: Python Wrapper And End-To-End Helper Coverage

**Owner:** Python integration agent.

**Repo:** `sase_102`.

**Goal:** verify the installed `sase lsp` path can serve jump-to-definition using helper-backed catalog data, not only
static Rust fixtures.

**Primary files:**

- `tests/main/test_lsp_handler.py`
- existing helper/catalog tests as needed
- optional new integration test under `tests/main/` or `tests/integrations/`

**Design:**

- Keep the existing `sase lsp` launcher unchanged unless Phase 1 introduces a new helper operation or environment
  variable.
- Add a focused test for the helper JSON shape containing the new `definition_path` field.
- Add an end-to-end smoke test if practical: start the Rust LSP through `SASE_XPROMPT_LSP_CMD` or `sase lsp`, open a
  temp prompt file, and request `textDocument/definition` for a temp xprompt catalog fixture.
- If a full subprocess LSP test is too brittle in Python, keep it in Rust and make Python verify the wrapper/environment
  contract only.

**Acceptance criteria:**

- Python helper output carries definition metadata for real files.
- The `sase lsp` wrapper still passes through `--version` and arbitrary server args.
- Backward compatibility with older clients consuming `source_path_display` is preserved.

**Verification:**

- `just install`
- targeted Python tests for catalog/helper/LSP wrapper
- `just check`

## Phase 5: Neovim Smoke, Docs, And Optional Convenience Mapping

**Owner:** Neovim client agent.

**Repo:** `../sase-nvim`.

**Goal:** prove the thin Neovim client can use the server's standard definition provider without adding duplicated
resolver logic.

**Primary files:**

- `lua/sase/lsp.lua`
- `tests/lsp_config.lua`
- `README.md`

**Design:**

- First verify that `vim.lsp.buf.definition()` works with the existing client setup and advertised server capability.
- Do not add custom path parsing in Lua.
- Add a convenience mapping only if the plugin already has a suitable keymap surface or documentation expectation.
  Otherwise document that users can use their normal LSP definition mapping.
- Add a test that the LSP client configuration does not disable definition capabilities.
- Update README troubleshooting/usage with a short note: with the LSP attached, normal editor go-to-definition opens the
  xprompt source file.

**Acceptance criteria:**

- Existing `setup({ lsp = ... })` starts the same server command and preserves completion behavior.
- Neovim smoke test can attach to the server and invoke a definition request, or the phase reports why the local test
  harness cannot drive a real Neovim LSP request.
- No legacy picker logic is expanded to handle jump-to-definition.

**Verification:**

- Run the repo's available Lua tests directly.
- Run `just check` if this repo has one by the time the phase is executed; otherwise report the exact test command and
  note the absence of a repo-level check target.

## Phase 6: Final Cross-Repo Validation

**Owner:** landing/validation agent.

**Repos:** `sase_102`, `../sase-core`, and `../sase-nvim`.

**Goal:** validate the whole feature as a user workflow and clean up any contract drift between phases.

**Checklist:**

- In a temp workspace, create `.xprompts/local.md`, reference `#local` in a Markdown prompt, and confirm
  `textDocument/definition` returns the local file URI.
- Reference a built-in xprompt and confirm the definition URI points to the package/default xprompt file when available.
- Reference a config-backed xprompt and confirm the URI points to the relevant config file when available.
- Reference an unknown xprompt and confirm diagnostics still warn while definition returns no target.
- Reference a plugin pseudo-source without a file and confirm no invalid URI is returned.
- Confirm hover still shows the display source string and completion still inserts canonical `#`/`#!` forms.

**Verification:**

- `sase_102`: `just install` then `just check`.
- `../sase-core`: full Rust fmt/clippy/test commands.
- `../sase-nvim`: available Lua/Neovim tests and manual smoke command notes.

## Implementation Notes For Phase Agents

- Preserve backward compatibility at every wire boundary. Optional new fields should default cleanly when absent.
- Treat `source_path_display` as presentation only.
- Prefer returning no definition over opening a surprising path.
- Avoid adding runtime-specific branches for Claude/Gemini/Codex/etc.; this feature is editor/LSP-only.
- Report exact commands run and any checks skipped.
