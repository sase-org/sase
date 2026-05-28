---
create_time: 2026-05-28 07:33:14
status: wip
prompt: sdd/prompts/202605/xprompt_lsp_description_warning.md
---
# Fix xprompt LSP description-field false warning

## Problem

Neovim reports this SASE xprompt LSP diagnostic for Markdown xprompt input metadata:

```text
Unknown xprompt input field `description` will be ignored
```

That diagnostic is wrong for current SASE semantics. Markdown xprompts support `description` both as a top-level
frontmatter field and as an optional input field in shortform and longform input definitions. The Python loader,
documentation, config schema, and current Rust source all agree on this.

## Findings

- The warning is emitted by the Rust xprompt LSP frontmatter diagnostics in `sase-core`, not by Neovim's YAML language
  server.
- Current `sase-core` source already accepts input descriptions and has unit coverage for block shortform and longform
  descriptions.
- I reproduced the user's warning through the active `sase lsp` wrapper on a Markdown xprompt containing:

  ```yaml
  input:
    topic:
      type: text
      description: Reading request or topic to search for.
  ```

- Launching the LSP from current `sase-core` source with `cargo run --manifest-path ... -p sase_xprompt_lsp --` returns
  no diagnostics for the same document.
- The active wrapper can exec a sibling `target/debug/sase-xprompt-lsp` binary directly before invoking Cargo. That
  bypasses Cargo's freshness check and lets Neovim keep using a stale LSP binary after the Rust source has been fixed.

## Plan

1. Update the Python `sase lsp` launcher so explicit overrides still win, but when a sibling `sase-core/Cargo.toml`
   exists and Cargo is available, the wrapper launches the LSP through
   `cargo run --manifest-path ... -p sase_xprompt_lsp --`.
2. Keep direct `target/debug` and `target/release` binary fallback for environments that have a built sibling binary but
   no Cargo executable.
3. Preserve packaged-binary behavior when no sibling Rust source tree is available by still falling back to
   `sase-xprompt-lsp` on `PATH`.
4. Add or adjust Python launcher tests to lock down the new resolution order and prevent regressions to stale direct
   target execution.
5. Add Rust diagnostic coverage for flow-style input descriptions if missing, so future parser changes continue to
   accept all documented input description forms.
6. Run focused Python and Rust tests, then run the required `just check` from the SASE repo after source edits.

## Validation

- Re-run the JSON-RPC reproduction against `sase lsp` after the launcher change and confirm the Markdown xprompt with an
  input `description` produces no diagnostics.
- Run `pytest tests/main/test_lsp_handler.py`.
- Run targeted `cargo test -p sase_core` tests for xprompt frontmatter diagnostics.
- Run `just install` if needed, then `just check` as required by this repo's agent instructions.
