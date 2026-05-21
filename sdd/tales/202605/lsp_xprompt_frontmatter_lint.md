---
create_time: 2026-05-21 18:36:53
status: wip
prompt: sdd/prompts/202605/lsp_xprompt_frontmatter_lint.md
---
# LSP XPrompt Frontmatter Lint Plan

## Goal

Add SASE xprompt LSP diagnostics for markdown xprompt frontmatter so an invalid input type such as:

```yaml
---
input:
  name: wordd
---
```

is flagged in the editor. The diagnostic should point at the invalid type token (`wordd`) instead of silently
normalizing it to `line`.

## Current Shape

- The executable LSP server lives in `../sase-core/crates/sase_xprompt_lsp`.
- It publishes diagnostics by calling `sase_core::editor_analyze_document()` from `server.rs`.
- Existing editor diagnostics live in `../sase-core/crates/sase_core/src/editor/diagnostics.rs` and currently cover
  unknown xprompt references, slash skills, directives, and xprompt call arguments.
- Markdown xprompt catalog loading parses frontmatter in `../sase-core/crates/sase_core/src/xprompt_catalog.rs`.
- Both Python and Rust currently coerce unknown xprompt input types to `line`; that behavior is useful for runtime
  tolerance but too quiet for authoring lint.
- The supported input type spellings are `word`, `line`, `text`, `path`, `int`/`integer`, `bool`/`boolean`, and `float`.

## Design

Implement this as editor diagnostics in `sase_core`, not in the LSP shell. That keeps linting behavior reusable by other
editor integrations and matches the Rust core boundary guidance.

Add a frontmatter-specific diagnostic pass to `editor::diagnostics::analyze_document()`:

1. Detect a YAML frontmatter block only when the document starts with a `---` delimiter and has a closing `---`.
2. Parse only the frontmatter text with `serde_yaml`, preserving the existing forgiving behavior when YAML is malformed.
3. Inspect only the top-level `input:` field:
   - Shortform map: `input: {name: word}` or nested block entries.
   - Longform sequence: `input: [{name: foo, type: word}]` or block list entries.
4. Validate explicit type strings against the supported input type aliases.
5. Emit an `Error` diagnostic with a stable code such as `invalid_xprompt_frontmatter_input_type` and a message that
   names the bad type and expected values.
6. Compute the range from source text so the diagnostic lands on the offending scalar. Start with a small frontmatter
   scanner that handles the xprompt forms SASE supports today:
   - `input:` shortform child mappings.
   - Nested `type:` fields under shortform entries.
   - Longform list entries with `type: ...`.
   - Flow-style shortform mappings where the invalid scalar can still be located textually.

Keep this lint narrowly scoped to markdown xprompt frontmatter for now. Do not change catalog/runtime parsing semantics
in this change; invalid types can continue to load as `line` while the editor reports the authoring error.

## Implementation Steps

1. In `../sase-core/crates/sase_core/src/editor/diagnostics.rs`, add constants/helpers for supported xprompt input type
   aliases and an `is_known_xprompt_input_type()` predicate.
2. Add a `frontmatter_diagnostics(document)` pass and call it from `analyze_document()` before normal body diagnostics.
3. Add a small frontmatter extractor that returns byte offsets for the YAML block within the full markdown document.
4. Add source-range helpers for frontmatter input type values:
   - Prefer exact byte ranges found from the YAML/frontmatter text.
   - Fall back to the whole `input` item or frontmatter block only if exact scalar localization is not possible.
5. Add focused unit tests in `editor/diagnostics.rs`:
   - Shortform `input.name: wordd` reports one error on `wordd`.
   - Valid aliases do not report.
   - Longform `- name: foo; type: wordd` reports.
   - Malformed YAML or documents without frontmatter do not panic or create unrelated diagnostics.
6. Add an LSP-level JSON-RPC test in `../sase-core/crates/sase_xprompt_lsp/tests/jsonrpc_stdio.rs` so opening a markdown
   document like `~/tmp/bad_pick_plan_xprompt.md` publishes a `sase-xprompt` diagnostic with the new code.

## Verification

Run focused Rust tests first:

```bash
cd ../sase-core
cargo test -p sase_core editor::diagnostics
cargo test -p sase_xprompt_lsp stdio_jsonrpc
```

Then run the Rust repo checks because this change modifies `../sase-core`:

```bash
cd ../sase-core
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
```

Because the Python wrapper repo's LSP command delegates to the Rust binary and no Python code is expected to change, a
full `just check` in this repo is only needed if implementation changes touch `sase_10` files beyond this plan artifact.
