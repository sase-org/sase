---
create_time: 2026-05-28 08:54:23
status: done
prompt: sdd/prompts/202605/xprompt_frontmatter_xprompts.md
---
# XPrompt Frontmatter `xprompts` LSP Plan

## Goal

Fix the Neovim/SASE xprompt LSP diagnostic:

```text
Unknown xprompt frontmatter field `xprompts` will be ignored
```

for files such as `xprompts/reads.md`, where Markdown frontmatter legitimately uses `xprompts:` to define local helper
prompts.

## Findings

- The Neovim plugin is not the source of this diagnostic. It starts the SASE xprompt LSP and configures
  YAML-language-server schemas for YAML files, but this specific message is emitted by the Rust editor diagnostic layer.
- The server implementation lives in the matching sibling workspace: `../sase-core/crates/sase_core` and
  `../sase-core/crates/sase_xprompt_lsp`.
- The diagnostic comes from `crates/sase_core/src/editor/frontmatter.rs`.
- `TOP_LEVEL_FIELDS` currently allows only: `name`, `input`, `tags`, `description`, `skill`, `snippet`, and `keywords`.
- The Python runtime already supports Markdown frontmatter `xprompts:` via `src/sase/xprompt/loader_sources.py`, where
  it is parsed as file-local xprompt definitions. Existing tests in `tests/test_user_frontmatter.py` verify that
  behavior.
- Rust catalog support already understands workflow-local `xprompts:` for YAML workflows. The immediate bug is that the
  editor frontmatter lint schema is stale for Markdown frontmatter.

## Implementation Plan

1. Update the Rust xprompt frontmatter validator in `../sase-core/crates/sase_core/src/editor/frontmatter.rs`. Add
   `xprompts` to the allowed top-level field list so valid Markdown frontmatter no longer receives the
   `unknown_xprompt_frontmatter_field` diagnostic.

2. Add a focused diagnostic regression test in `../sase-core/crates/sase_core/src/editor/diagnostics.rs`. The test
   should use a Markdown frontmatter block shaped like `xprompts/reads.md`:

   ```yaml
   ---
   description: Example
   input:
     topic: text
   xprompts:
     _helper:
       content: Helper {{ topic }}
   ---
   Body
   ```

   It should assert that no `unknown_xprompt_frontmatter_field` diagnostic is emitted for `xprompts`.

3. Keep this fix deliberately narrow. Do not move validation into the Neovim plugin, and do not change YAML
   language-server schema registration. This is not a `yamlls` schema error. Do not change runtime parsing behavior
   unless the focused test exposes a server/runtime mismatch beyond the stale allowed-field list.

4. Optionally add a lightweight LSP JSON-RPC regression in `../sase-core/crates/sase_xprompt_lsp/tests/jsonrpc_stdio.rs`
   only if the unit test does not sufficiently cover the surfaced diagnostic. The existing JSON-RPC frontmatter test
   already verifies diagnostic publication, so the unit-level coverage should be enough for this narrow schema fix.

## Verification

Run focused Rust tests first:

```bash
cd ../sase-core
cargo test -p sase_core editor::diagnostics
```

Then run formatting and the LSP smoke/regression test package if the focused test passes:

```bash
cd ../sase-core
cargo fmt --all -- --check
cargo test -p sase_xprompt_lsp stdio_jsonrpc_frontmatter_diagnostics
```

If only `../sase-core` files change, the Python `sase_10` workspace does not need a full `just check`; the relevant
checks are the Rust package tests above.
