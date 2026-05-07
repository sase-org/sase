---
create_time: 2026-05-07 03:37:14
status: done
prompt: sdd/prompts/202605/xprompt_lsp_server.md
bead_id: sase-2a
tier: epic
---
# Plan: XPrompt LSP Server And Thin `sase-nvim`

## Context

The goal is to move editor-facing xprompt intelligence out of `../sase-nvim` and into a reusable LSP server owned by
`../sase-core`, while improving the user experience with directive completion, hover, diagnostics, and
jump-to-definition. The Neovim plugin should become a thin client that starts the server, enables completion, and keeps
optional picker UI where it adds value. Other editors should be able to support xprompts by speaking standard LSP
instead of porting the Lua/TUI logic again.

The research file to keep beside this plan is `sdd/research/202605/xprompt_lsp_server_research.md`. Its key
recommendation is correct: build a Rust LSP server now, but do not immediately port the full Python xprompt loader. V1
should use the existing structured xprompt catalog bridge and cache aggressively. Moving catalog loading into Rust
should be a later phase, behind the same editor-facing API.

## Current Shape

`../sase-nvim` currently owns more than UI glue:

- `lua/sase/complete/_token.lua` duplicates TUI token and completion-mode detection.
- `lua/sase/xprompt.lua` shells out to `sase xprompt list` and reconstructs insertion behavior.
- `lua/sase/complete/file.lua` shells out to `sase file list`.
- `lua/sase/complete/file_history.lua` shells out to `sase file-history list/delete`.
- `plugin/sase_yamlls.lua` shells out to `sase path` and mutates `yamlls` configuration.

The Python repo already has structured catalog data in `src/sase/xprompt/_catalog_models.py`,
`src/sase/xprompt/_catalog_structured.py`, and `src/sase/integrations/_mobile_helper_catalog.py`. This is the right V1
source for xprompt names, canonical `#` vs `#!` insertion, slash skill metadata, argument metadata, previews, and source
path display.

`../sase-core` currently has `sase_core`, `sase_core_py`, and `sase_gateway`. The gateway contains useful reusable host
bridge code in `crates/sase_gateway/src/host_bridge.rs`, but no LSP crate. The new work should preserve the core
boundary: shared editor/backend behavior belongs in Rust core; presentation, keymaps, and optional Neovim-specific UI
stay in `sase-nvim`.

## Product Decisions

- Server crate/binary: add `crates/sase_xprompt_lsp` in `../sase-core`. The advertised LSP name should be
  `sase-xprompt-lsp`.
- Public launch command: support a standalone `sase-xprompt-lsp` binary for Rust/dev usage and add a Python `sase lsp`
  wrapper later so users do not need a second install step.
- Protocol: target stable LSP 3.17-compatible capabilities. Avoid proposed-only 3.18 behavior.
- Rust LSP dependency: use `tower-lsp-server` unless the implementing agent finds a concrete blocker; document
  `async-lsp` as the fallback.
- Catalog source: V1 calls the existing structured helper bridge with `include_pdf=false`, then caches in the LSP.
- Schema support: keep `yamlls` registration in a small Neovim shim for V1. Do not turn SASE LSP into a YAML schema
  validator yet.
- Plugin migration: default to `completion_backend = "auto"` after the LSP is installable. Auto means LSP when
  available, legacy helper pickers otherwise. Do not create a flag day.

## Dependency Graph

1. Phase 1 unblocks shared bridge reuse.
2. Phase 2 depends on Phase 1 only for final wire names, but can mostly proceed in pure `sase_core`.
3. Phase 3 depends on Phases 1 and 2.
4. Phase 4 depends on Phase 3 and touches the Python repo for install/launch.
5. Phase 5 depends on Phase 3 and can run before or after Phase 4 if the binary is invoked directly.
6. Phase 6 depends on Phases 3 and 4 for the normal user path.
7. Phase 7 depends on Phase 6.
8. Phase 8 depends on stabilized contracts from Phases 1-7.

Phases 1-7 are the practical MVP path. Phase 8 is deliberately last because catalog loading is semantically deep and
plugin-extensible.

## Verification Rules

Every phase agent should report the exact commands it ran.

- In `sase_101`: run `just install` before checks if the workspace may be stale, then run targeted tests and
  `just check` for any non-bead file changes.
- In `../sase-core`: run `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`, and
  `cargo test --workspace`.
- In `../sase-nvim`: there is currently no `Justfile` or CI config. Run any added tests directly, run a Neovim smoke
  test where possible, and clearly state the absence of a repo-level `just check` target. If a phase adds a `just check`
  target, use it for later plugin phases.

## Phase 1: Lift Host Bridge And Define Editor Wire Contracts

**Owner:** `../sase-core` bridge/core agent.

**Goal:** make the structured xprompt catalog bridge reusable by both the gateway and the new LSP, without making the
LSP depend on HTTP gateway internals.

**Repos:** `../sase-core`.

**Primary files:**

- `Cargo.toml`
- `crates/sase_core/src/lib.rs`
- new `crates/sase_core/src/host_bridge.rs` or new crate `crates/sase_host_bridge`
- `crates/sase_gateway/src/host_bridge.rs`
- `crates/sase_gateway/src/wire.rs`
- `crates/sase_gateway/src/lib.rs`

**Deliverables:**

1. Move or extract the shared portions of `HelperHostBridge`, `DynHelperHostBridge`, `CommandHelperHostBridge`,
   `StaticHelperHostBridge`, and `HostBridgeError` into a place the LSP can depend on without pulling `axum` or gateway
   storage.
2. Move or mirror only the needed helper wire structs for editor use: `MobileXpromptCatalogRequestWire`,
   `MobileXpromptCatalogResponseWire`, catalog entries, skipped rows, result metadata, and stats.
3. Keep `sase_gateway` behavior unchanged by re-exporting or adapting the moved types.
4. Add editor-oriented wire aliases if useful, but do not rename the JSON fields yet. The Python helper already emits
   the mobile shape; compatibility matters more than naming purity in this phase.
5. Add timeout-ready bridge entry points or a clearly documented wrapper seam. The current `wait_with_output()` has no
   timeout; the LSP must be able to wrap bridge calls with `tokio::time::timeout`.
6. Add deterministic tests that prove `StaticHelperHostBridge` can return a structured catalog response from the new
   location.

**Non-goals:**

- No LSP crate yet.
- No xprompt parsing or completion behavior yet.
- No Python CLI changes yet unless a compile break forces a tiny compatibility adjustment.

**Done when:**

- `sase_gateway` compiles and its existing tests still pass.
- The shared bridge has no dependency on gateway HTTP routing, push notification code, or storage.
- `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`, and `cargo test --workspace`
  pass in `../sase-core`.

## Phase 2: Core Editor Analyzer MVP

**Owner:** `../sase-core` analyzer agent.

**Goal:** port the duplicated editor rules into pure, testable Rust APIs under `sase_core`, independent of JSON-RPC/LSP.

**Repos:** `../sase-core`; read-only reference to `sase_101` and `../sase-nvim`.

**Primary files:**

- new `crates/sase_core/src/editor/mod.rs`
- new `crates/sase_core/src/editor/token.rs`
- new `crates/sase_core/src/editor/completion.rs`
- new `crates/sase_core/src/editor/file.rs`
- new `crates/sase_core/src/editor/directive.rs`
- new `crates/sase_core/src/editor/diagnostics.rs`
- new `crates/sase_core/src/editor/hover.rs`
- new `crates/sase_core/src/editor/wire.rs`
- tests under `crates/sase_core/tests/` or module tests beside the implementation

**Reference behavior:**

- `../sase-nvim/lua/sase/complete/_token.lua`
- `sase_101/src/sase/ace/tui/widgets/file_completion.py`
- `sase_101/src/sase/ace/tui/widgets/xprompt_completion.py`
- `sase_101/src/sase/ace/tui/widgets/xprompt_arg_assist.py`
- `sase_101/docs/xprompt.md#directives`
- `../sase-core/crates/sase_core/src/agent_launch/mod.rs` for directive parser precedent

**Deliverables:**

1. `DocumentSnapshot` and byte/line position helpers that can safely map LSP positions to byte ranges for ASCII prompt
   text. Handle non-ASCII defensively even if initial tests are ASCII-heavy.
2. `extract_token_at_position()` with parity for: `#`, `#!`, `#foo`, `/skill`, `@src/foo`, `./src/foo`, `../foo`,
   `.sase/foo`, `~/foo`, absolute paths, empty cursor, delimiters, and mid-token cursors.
3. `classify_completion_context()` returning contexts for xprompt, slash skill, file path, file history, xprompt
   argument name/value, directive name, and directive argument.
4. File candidate generation ported from Python: dotfile filtering, symlinked directories as directories,
   directory-first sort, `@` prefix preservation, and shared prefix extension where useful.
5. Xprompt candidate filtering over structured catalog entries: canonical insertion from catalog, `#!` filtering, slash
   skill filtering, replacement ranges, and simple detail fields.
6. Directive completion metadata for `%model`, `%name`, `%wait`, `%approve`, `%edit`, `%plan`, `%epic`, `%hide`, `%tag`,
   `%repeat`, `%alt`, `%xprompts_enabled`, and known aliases such as `%m`, `%n`, `%w`, `%a`, `%e`, `%p`, `%t`, and
   `%(...)`.
7. Narrow xprompt argument context detection for the forms already supported by the TUI: `#foo:`, `#!foo:`, `#foo(`,
   `#foo(arg=`, HITL suffixes `!!` and `??`, and namespaced `ns/foo` / `ns__foo`.
8. Initial pure diagnostics: unknown xprompt, canonical marker mismatch, unknown slash skill, malformed narrow argument
   form, and unknown directive where the analyzer is confident.
9. Initial hover payload construction for xprompt refs, active xprompt inputs, and directives.

**Tests:**

- Golden tests for token extraction and classification.
- Golden tests for file completion ordering and `@` prefix behavior.
- Fixture catalog tests for xprompt, slash skill, directive, and argument completion.
- Tests must include examples from the research file and from `docs/xprompt.md`.

**Non-goals:**

- No subprocess calls.
- No LSP-specific structs.
- No full launch-time xprompt expansion validation. Python remains authoritative.

**Done when:**

- `sase_core::editor` exposes a stable enough API for Phase 3 to convert to LSP types.
- `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`, and `cargo test --workspace`
  pass in `../sase-core`.

## Phase 3: LSP Skeleton With Completion

**Owner:** `../sase-core` LSP agent.

**Goal:** add a working stdio LSP server that can be driven by generic editors and returns completion from the Phase 2
analyzer.

**Repos:** `../sase-core`.

**Primary files:**

- `Cargo.toml`
- new `crates/sase_xprompt_lsp/Cargo.toml`
- new `crates/sase_xprompt_lsp/src/main.rs`
- new `crates/sase_xprompt_lsp/src/server.rs`
- new `crates/sase_xprompt_lsp/src/catalog_cache.rs`
- new `crates/sase_xprompt_lsp/src/lsp_convert.rs`
- new `crates/sase_xprompt_lsp/src/logging.rs`
- new integration tests under `crates/sase_xprompt_lsp/tests/`

**Deliverables:**

1. Workspace member `crates/sase_xprompt_lsp` using `tower-lsp-server`, `lsp-types`, `tokio`, `tracing`, and
   `tracing-subscriber`.
2. Stdio server with `initialize`, `initialized`, `shutdown`, `exit`, incremental or full text sync, and a document
   cache.
3. Completion support for: xprompt refs, slash skills, file paths, recent files, directive names, directive arguments
   where known, xprompt arg names, and xprompt arg skeletons gated on client snippet support.
4. Catalog cache keyed by root/project context with: startup refresh, lazy fallback refresh, manual refresh command,
   short TTL, and `include_pdf=false`.
5. Host bridge calls wrapped in timeouts: 5 seconds for completion-path refresh, 30 seconds for explicit refresh.
6. Graceful degraded behavior: missing `sase`, malformed helper JSON, helper timeout, and non-zero helper exits should
   log to stderr, send at most one user-facing warning per failure class, and return empty/incomplete completion instead
   of crashing.
7. LSP capability negotiation: snippet support, completion item resolve support, completion tags, code action literal
   support placeholders for later phases.
8. `completionItem/resolve` if useful for expensive preview/detail fields; otherwise include bounded detail eagerly.
9. Logging that never writes protocol noise to stdout. Add `#![deny(clippy::print_stdout)]` or equivalent protection.

**Tests:**

- Unit tests for LSP range/text-edit conversion.
- Service-level tests using a static host bridge and fixture documents.
- At least one stdio-style JSON-RPC smoke test for initialize plus completion.

**Non-goals:**

- No Neovim integration yet.
- No Python `sase lsp` wrapper yet.
- Hover/diagnostics/code actions may remain stubs unless needed for completion internals.

**Done when:**

- `cargo run -p sase_xprompt_lsp -- --version` or equivalent works.
- A local JSON-RPC smoke test can request completion for `#fo|`, `%mo|`, and `./sr|`.
- `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`, and `cargo test --workspace`
  pass in `../sase-core`.

## Phase 4: Python Launch/Distribution Surface

**Owner:** `sase_101` Python integration agent.

**Goal:** make the LSP startable through the normal `sase` command and give the Rust server a clear helper bridge
surface.

**Repos:** `sase_101`; may need small coordinated changes in `../sase-core` packaging docs.

**Primary files to inspect:**

- `pyproject.toml`
- `Justfile`
- `src/sase/cli/parser_commands.py`
- `src/sase/main/entry.py`
- `src/sase/integrations/_mobile_helper_bridge.py`
- `src/sase/integrations/_mobile_helper_catalog.py`
- existing CLI tests around xprompt/list/helper commands

**Deliverables:**

1. Add a `sase lsp` subcommand that launches the LSP. Prefer `exec` into a bundled or discoverable Rust binary so stdio
   remains clean and signals behave correctly.
2. Add `SASE_XPROMPT_LSP_CMD` override support for development. Example value:
   `cargo run --manifest-path ../sase-core/Cargo.toml -p sase_xprompt_lsp --`.
3. Decide whether to add `sase editor helper-bridge xprompt-catalog` as an alias for the existing mobile helper. If it
   is cheap, add the alias so editor code is not branded as mobile forever. If not, document that the LSP intentionally
   uses the mobile bridge shape for V1.
4. Ensure the helper catalog returns all fields Phase 3 consumes: `name`, `display_label`, `insertion`,
   `reference_prefix`, `kind`, `description`, `source_bucket`, `project`, `tags`, `input_signature`, `inputs`,
   `is_skill`, `content_preview`, and `source_path_display`.
5. Add `sase path` or new helper coverage only if the LSP needs schema association or binary discovery data in V1.
6. Document install/dev usage in the appropriate docs: `docs/xprompt.md`, `docs/ace.md`, or a small new editor/LSP
   section.

**Tests:**

- CLI parser/handler tests for `sase lsp --version` or `sase lsp --help`.
- Helper bridge JSON contract tests for the editor alias if added.
- A subprocess smoke test may use a fake LSP command through `SASE_XPROMPT_LSP_CMD` rather than starting the real
  server.

**Non-goals:**

- Do not port xprompt catalog loading to Rust here.
- Do not make Neovim depend on packaging details that are not yet available to other editors.

**Done when:**

- `sase lsp --version` or `sase lsp --help` works from the local venv.
- The server can still be run directly from cargo for development.
- `just install`, targeted tests, and `just check` pass in `sase_101`.

## Phase 5: Rich LSP Features

**Owner:** `../sase-core` LSP feature agent.

**Goal:** add the features that make the LSP clearly better than the old plugin helpers: directive completion, hover,
diagnostics, code actions, and jump-to-definition.

**Repos:** `../sase-core`; read-only reference to `sase_101` docs/parser behavior.

**Primary files:**

- `crates/sase_core/src/editor/*`
- `crates/sase_xprompt_lsp/src/server.rs`
- `crates/sase_xprompt_lsp/src/lsp_convert.rs`
- `crates/sase_xprompt_lsp/src/catalog_cache.rs`
- LSP tests

**Deliverables:**

1. `textDocument/hover`: xprompt refs show kind, canonical insertion, description, inputs, tags, source display, and
   bounded preview; directive hovers show syntax and behavior; active argument positions show the active input.
2. Diagnostics: unknown `#name` / `#!name`, canonical marker mismatch, unknown slash skill, unknown directive, malformed
   narrow argument contexts, and helper/catalog failure diagnostics on a synthetic URI if appropriate.
3. Code actions: replace `#foo` with `#!foo` or the reverse when catalog says so, insert required named-arg skeleton,
   insert colon arg skeleton, refresh catalog, and open xprompt source when safe.
4. `textDocument/definition`: jump from `#foo`, `#!foo`, and `/skill` to the local xprompt source when
   `source_path_display` resolves to a safe local file. If a source is not local or cannot be trusted, return no
   definition rather than guessing.
5. Directive completion: complete `%model`, `%name`, `%wait`, `%approve`, `%edit`, `%plan`, `%epic`, `%hide`, `%tag`,
   `%repeat`, `%alt`, `%xprompts_enabled`, aliases, and `%(...)` shorthand. Include argument placeholder variants only
   when snippet support exists.
6. Optional inlay hints: add only if the implementation is straightforward after argument context work; otherwise leave
   documented as V2.
7. `workspace/didChangeWatchedFiles` and/or manual invalidation: invalidate catalog for `xprompts/**/*.md`,
   `xprompts/**/*.yml`, `xprompts.yml`, `xprompts.yaml`, `sase.yml`, and `~/.sase/file_reference_history.json` where
   clients support watching.

**Tests:**

- Hover golden tests for xprompt, directive, and active argument.
- Diagnostics golden tests.
- Code action tests with exact workspace edits.
- Definition tests with safe local and non-local source cases.
- End-to-end LSP request tests for completion, hover, diagnostics, codeAction, and definition.

**Non-goals:**

- Do not implement full semantic tokens unless the phase finishes early and tests are still clean.
- Do not validate complete launch semantics; keep launch-time Python authoritative.

**Done when:**

- `textDocument/definition` can jump from a known xprompt reference to its source in fixture tests.
- `%` directive completion works in the same completion path as xprompt completion.
- `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`, and `cargo test --workspace`
  pass in `../sase-core`.

## Phase 6: Neovim LSP Client MVP

**Owner:** `../sase-nvim` client agent.

**Goal:** make `sase-nvim` start and use the LSP while preserving the existing public API and legacy fallback.

**Repos:** `../sase-nvim`.

**Primary files:**

- `lua/sase/init.lua`
- new `lua/sase/lsp.lua`
- `lua/sase/complete.lua`
- `plugin/sase_complete.lua`
- `plugin/sase_xprompt.lua`
- `plugin/sase_yamlls.lua`
- `README.md`
- tests under `tests/` if added

**Deliverables:**

1. Extend setup without breaking existing config:
   `require("sase").setup({ complete = { keymap = true }, lsp = { enabled = true, cmd = nil } })`.
2. Add `completion_backend = "auto" | "lsp" | "legacy"` under `complete`, defaulting conservatively during this phase.
   If unsure, keep default as legacy until Phase 7.
3. Start the server with `vim.lsp.start` when enabled: use `cmd = opts.lsp.cmd`, else `SASE_XPROMPT_LSP_CMD`, else
   `{ "sase", "lsp" }`, falling back to `{ "sase-xprompt-lsp" }` if appropriate.
4. Choose root with `vim.fs.root(0, { ".sase", ".git" })` when available, with a Neovim 0.8-compatible fallback.
5. Attach to useful buffers without being noisy: `markdown`, `gitcommit`, `sase`, and an optional prompt-specific
   filetype. Let the server return empty completions outside SASE token contexts.
6. Enable built-in LSP completion when available. Preserve `<C-t>` as a manual completion trigger and keep the legacy
   dispatcher available.
7. Keep these existing surfaces working: `setup({ complete = { keymap = true } })`, `:SaseXPrompts`,
   `:SaseXPromptsRefresh`, `:SaseFileHistoryRefresh`, and the `#@` trigger.
8. Keep `plugin/sase_yamlls.lua` as a small schema-registration shim for now.

**Tests and smoke checks:**

- Add Lua tests for config merging and command selection if the test harness is practical.
- Manual Neovim smoke: open a Markdown buffer, type `#`, request completion, verify xprompt items; type `%`, verify
  directive items; hover over a known xprompt; jump to definition on a fixture/source-backed xprompt; verify legacy
  fallback still opens the old picker when the LSP command is unavailable.

**Non-goals:**

- Do not delete the legacy Lua completion logic in this phase.
- Do not replace Telescope browse commands yet.

**Done when:**

- A user can opt into LSP-backed completion from `sase-nvim`.
- Existing documented plugin usage still works.
- Available plugin tests or smoke checks pass, and the final report notes whether a repo-level `just check` exists.

## Phase 7: Thin `sase-nvim` Migration And Cleanup

**Owner:** `../sase-nvim` migration agent.

**Goal:** make the LSP path the normal path and remove duplicated logic from the plugin once parity is proven.

**Repos:** `../sase-nvim`; may need small docs updates in `sase_101`.

**Primary files:**

- `lua/sase/complete/_token.lua`
- `lua/sase/complete/file.lua`
- `lua/sase/complete/file_history.lua`
- `lua/sase/complete/xprompt.lua`
- `lua/sase/xprompt.lua`
- `lua/telescope/_extensions/sase.lua`
- `plugin/sase_complete.lua`
- `README.md`

**Deliverables:**

1. Switch `completion_backend = "auto"` to prefer LSP when `sase lsp` or `sase-xprompt-lsp` is available.
2. Reduce `lua/sase/complete/_token.lua` to compatibility-only code or delete it if no public path needs it.
3. Keep Telescope browse commands, but source xprompt data from the same catalog contract as the LSP where practical. If
   this requires custom LSP requests that are not yet implemented, keep the helper call and document why.
4. Preserve file-history deletion UX. Prefer an LSP command if available; otherwise keep the existing CLI helper.
5. Update README so users understand: LSP-backed completion, fallback behavior, required `sase` command, optional
   standalone binary, and troubleshooting logs.
6. Remove stale docs that claim the plugin mirrors the TUI in Lua.
7. Add or update tests for fallback selection and command behavior.

**Non-goals:**

- Do not remove `:SaseXPrompts` or `#@`.
- Do not remove the YAML-LS schema shim unless another editor-neutral schema solution has landed.

**Done when:**

- The plugin no longer owns xprompt/file/directive token classification for the normal completion path.
- Existing users who never enable the LSP still have a documented fallback.
- Available plugin tests or smoke checks pass, and the final report notes whether a repo-level `just check` exists.

## Phase 8: Rust XPrompt Catalog Loader Migration

**Owner:** cross-repo core migration agent.

**Goal:** remove the Python helper subprocess from the LSP hot path by moving xprompt catalog loading into Rust behind
the same editor API.

**Repos:** `../sase-core` and `sase_101`.

**Primary references:**

- `sase_101/src/sase/xprompt/_catalog_sources.py`
- `sase_101/src/sase/xprompt/_catalog_structured.py`
- `sase_101/src/sase/xprompt/reference_display.py`
- `sase_101/src/sase/xprompt/_parsing*.py`
- `sase_101/src/sase/xprompt/workflow_models.py`
- existing xprompt catalog, parser, and workflow tests

**Deliverables:**

1. Port discovery and structured catalog projection into Rust while preserving the Phase 1 editor wire contract.
2. Preserve canonical insertion behavior exactly, especially: standalone workflows and multi-agent Markdown xprompts use
   `#!`; inline-capable prompts use `#`; slash skills insert as `/name` in skill contexts.
3. Preserve input metadata behavior: step inputs excluded, requiredness based on unset defaults, simple default display
   values, sorted tags, bounded content preview, and safe source path display.
4. Add Python-to-Rust parity fixtures for representative built-in, project, config, plugin, memory, skill, YAML
   workflow, Markdown prompt, namespaced, and multi-agent xprompts.
5. Update the LSP to prefer the Rust catalog and fall back to the helper bridge on unsupported/plugin-defined sources if
   needed.
6. Keep the Python helper bridge stable for mobile and older clients until they migrate.

**Non-goals:**

- Do not remove the Python xprompt implementation outright.
- Do not break plugin-defined xprompts. If plugin discovery cannot be ported safely in one phase, use a hybrid catalog
  with clear source attribution.

**Done when:**

- Warm and cold completion no longer require a Python subprocess for supported catalog sources.
- Python/Rust parity tests cover the catalog fields consumed by the LSP.
- `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`, and `cargo test --workspace`
  pass in `../sase-core`.
- `just install`, targeted xprompt/catalog tests, and `just check` pass in `sase_101` for any Python changes.

## Cross-Phase Risks

- The helper bridge is one subprocess per request today. Phases 3 and 5 must avoid per-keystroke subprocess calls by
  caching and refreshing in the background.
- LSP stdout corruption is easy. The LSP crate must never use `println!`; all logs go to stderr through tracing.
- Client capabilities differ. Always gate snippets, code action literals, item tags, and resolve behavior.
- `source_path_display` is display-oriented. Definition/code-action source opening must only use paths that resolve
  safely to local files.
- Schema association is not a generic LSP feature. Keep YAML-LS integration small and separate until a second editor
  proves a better cross-editor contract.
- Directive parsing already exists in Rust launch planning, but much of it is private. Expose only stable editor
  metadata and narrow parser helpers; do not accidentally couple LSP completion to launch fan-out internals.
- Do not remove legacy plugin behavior before Phase 6 proves the LSP works in Neovim and Phase 7 documents fallback.

## MVP Acceptance Criteria

After Phases 1-7:

- `sase lsp` starts a stdio LSP server.
- Neovim can use LSP completion for `#xprompt`, `#!standalone`, `/skill`, `%directive`, file paths, recent files, and
  xprompt argument names.
- Hover works for known xprompts and directives.
- Jump-to-definition works for xprompts with safe local sources.
- Diagnostics identify unknown xprompts and canonical marker mismatches without blocking typing.
- `sase-nvim` retains its existing public commands and key setup, but the normal completion path no longer duplicates
  xprompt/file/directive analysis in Lua.
- The same LSP server can be documented for VS Code, Zed, Helix, or other editors without asking those clients to port
  SASE-specific parsing logic.
