---
create_time: 2026-05-28 09:22:07
status: done
prompt: sdd/prompts/202605/lsp_local_xprompts.md
---
# Plan: LSP Support for Markdown-Local XPrompts

## Goal

Fix the SASE xprompt LSP so Markdown xprompt files that define local helpers in frontmatter, such as
`xprompts/reads.md`, do not report helper references like `#_article_search_agent` as unknown. The editor behavior
should match the Python runtime path: frontmatter-local helpers are private to their owning xprompt file, valid inside
that file's body, and not exposed as global catalog entries.

## Findings

- `xprompts/reads.md` defines `_article_search_agent` under frontmatter `xprompts:` and uses `#_article_search_agent` in
  the multi-agent body.
- The Python runtime already preserves these helpers on `XPrompt.local_xprompts` and expands them before multi-agent
  segment splitting.
- The LSP is implemented in the Rust `sase-core` sibling workspace, primarily under `crates/sase_core/src/editor/*`,
  `crates/sase_core/src/xprompt_catalog.rs`, and `crates/sase_xprompt_lsp/src/server.rs`.
- The Rust frontmatter lint accepts `xprompts` as a top-level field, but the diagnostic pass currently validates every
  `#name` reference only against the global assist catalog.
- The Rust markdown catalog loader also does not currently parse Markdown frontmatter `xprompts:` into the owning
  xprompt's local-helper model, while YAML workflows already have `local_xprompts`.

## Implementation Approach

1. Add Rust-side representation for Markdown-local helpers.
   - Extend `CatalogXprompt` with `local_xprompts: Vec<CatalogXprompt>`.
   - Parse frontmatter `xprompts:` in `load_xprompt_from_markdown()` using the same config-entry syntax already used for
     YAML workflow-local helpers.
   - Preserve local helpers when converting a `CatalogXprompt` into a `CatalogWorkflow`.
   - Keep helper names private; do not add `_...` helpers as standalone catalog entries.

2. Teach diagnostics about current-document local helpers.
   - Parse the open document's frontmatter for local helper names.
   - Treat those names as known only while analyzing that same document.
   - Apply the same argument diagnostics for local helper calls when the local helper declares inputs.
   - Preserve existing warnings for truly unknown global references and for local helper names that are not declared in
     the current document.

3. Keep LSP behavior scoped and predictable.
   - Avoid making private helper names visible in normal completion lists unless completion is explicitly for the
     current document body and can be implemented without leaking helpers globally.
   - Ensure the canonical marker check does not force `#!` or another global marker policy onto local helper calls.
   - Leave the frontmatter field-shape linting separate unless a small validation addition is required for local helper
     input metadata.

4. Add focused Rust tests.
   - `sase_core::editor::diagnostics`: a Markdown document with frontmatter `xprompts: _helper` and body `#_helper`
     produces no `unknown_xprompt`.
   - The same test should cover helper input metadata so `#_helper` can produce a missing-required-arg diagnostic and
     `#_helper(arg)` is accepted.
   - A reference to an undeclared `_missing` in the same document still produces `unknown_xprompt`.
   - `sase_core::xprompt_catalog`: Markdown frontmatter local helpers are parsed and searchable through the owning
     catalog entry's workflow-local metadata, without creating a separate `_helper` entry.
   - `sase_xprompt_lsp`: `diagnostics_for_uri_text()` on a file under `xprompts/` with a local helper reference does not
     publish an unknown-xprompt diagnostic.

5. Verify.
   - In `sase-core`, run targeted tests first:
     `cargo test -p sase_core xprompt_catalog::tests::parses_xprompt_workflow_and_input_descriptions` plus the new
     diagnostics/catalog tests, and the relevant `sase_xprompt_lsp` diagnostic test.
   - Then run the Rust workspace checks expected by the sibling repo: `cargo fmt --all -- --check`,
     `cargo clippy --workspace --all-targets -- -D warnings`, and `cargo test --workspace`.
   - Because this primary `sase` workspace will have a plan file change, run `just install` if needed and `just check`
     before the final response, per the repo instructions.

## Risks

- The LSP catalog currently flows through wire structs that do not expose local helpers. The diagnostics fix should not
  require changing mobile/editor wire contracts unless tests show argument hints or hover need helper metadata from the
  catalog rather than from the current document.
- Markdown frontmatter parsing in Rust is intentionally lightweight. The local-helper parser should mirror existing
  behavior enough for diagnostics and catalog metadata without trying to become the full Python renderer.
- Project namespacing should continue to apply only to the owning xprompt entry, not to private helper names.
