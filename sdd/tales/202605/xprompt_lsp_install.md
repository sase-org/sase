---
create_time: 2026-05-28 10:03:13
status: wip
prompt: sdd/prompts/202605/xprompt_lsp_install.md
---
# Plan: Install Fresh `sase-xprompt-lsp` During Local SASE Updates

## Problem

The `xprompts/reads.md` diagnostics are real from the live editor path, but they are not caused by invalid Markdown
frontmatter anymore.

Current source in `/home/bryan/projects/github/sase-org/sase-core` already has both fixes that `reads.md` needs:

- `crates/sase_core/src/editor/frontmatter.rs` allows the `xprompts` top-level frontmatter field.
- `crates/sase_core/src/editor/diagnostics.rs` merges current-document frontmatter local xprompts before reporting
  unknown xprompt references.
- `crates/sase_xprompt_lsp/src/server.rs` has an LSP regression for `_article_search_agent`.

The live `sase lsp` JSON-RPC probe against `/home/bryan/projects/github/sase-org/sase/xprompts/reads.md` still emits:

```text
Unknown xprompt frontmatter field `xprompts` will be ignored
Unknown xprompt `_article_search_agent`
```

The observed root cause is executable skew:

- `sase-xprompt-lsp` is not installed on `PATH`.
- `sase lsp --version` still succeeds by falling back to
  `/home/bryan/projects/github/sase-org/sase-core/target/debug/sase-xprompt-lsp`.
- That binary was built at `2026-05-28 07:55`, while the relevant Rust source files were updated later at
  `2026-05-28 09:11` and `2026-05-28 09:34`.
- Neovim correctly resolves to `sase lsp`, but `sase lsp` is executing the stale fallback binary.

The local update script is the missing durable fix. `install_sase_github` syncs the sibling repos, reinstalls the Python
uv-tool package, and rebuilds/installs `sase_core_rs` into the uv-tool venv, but it does not install or rebuild
`sase-xprompt-lsp`. Any LSP-only Rust change can therefore remain invisible until a manual cargo build happens in the
right checkout.

## Goals

- Make `install_sase_github` leave a fresh `sase-xprompt-lsp` executable on `PATH`.
- Make normal Neovim startup use that installed binary through the existing `sase lsp` wrapper resolution.
- Keep development overrides (`SASE_XPROMPT_LSP_CMD`) intact.
- Keep the change narrow and avoid changing `xprompts/reads.md`, since the file is using supported local xprompt
  frontmatter.
- Verify the live `sase lsp` JSON-RPC path, not only unit tests.

## Non-Goals

- Do not remove the `target/debug` fallback from `sase lsp` in this pass; it remains useful for first-time development
  checkouts.
- Do not move this validation into the Neovim plugin. The plugin is resolving the wrapper correctly.
- Do not broaden the xprompt frontmatter schema again; the schema/source fix already exists.

## Implementation Plan

1. Update the chezmoi-managed installer source:

   ```text
   /home/bryan/.local/share/chezmoi/home/bin/executable_install_sase_github
   ```

   Add an `install_xprompt_lsp` helper that runs after repo sync has established the current `sase-core` checkout:

   ```bash
   install_xprompt_lsp() {
       if ! command -v cargo >/dev/null 2>&1; then
           echo "ERROR: cargo not on PATH; cannot install sase-xprompt-lsp." >&2
           return 1
       fi
       echo ">>> Installing sase-xprompt-lsp into cargo bin..."
       cargo install --path "$SASE_CORE_DIR/crates/sase_xprompt_lsp" --bin sase-xprompt-lsp --locked --force
   }
   ```

   This installs to the normal cargo bin directory (`~/.cargo/bin` on this machine), which is already before
   `~/.local/bin` in `PATH`.

2. Call `install_xprompt_lsp` before the post-install health probe. The script already keeps axe in maintenance/stopped
   state during the install window, so the LSP install belongs inside the same protected section.

3. Extend `probe_uv_tool_health` with a lightweight LSP availability check:

   ```bash
   sase lsp --version
   command -v sase-xprompt-lsp
   ```

   Keep the deeper JSON-RPC probe as manual verification rather than embedding a long Python script in the installer.

4. Apply the chezmoi change so `/home/bryan/bin/install_sase_github` is updated.

5. Install the fresh LSP binary immediately, either by rerunning `install_sase_github` or by running the same
   `cargo install --path "$SASE_CORE_DIR/crates/sase_xprompt_lsp" --bin sase-xprompt-lsp --locked --force` command once
   after the script change. The immediate install fixes the currently running machine; the script change prevents the
   skew from returning after future updates.

6. Re-run the live JSON-RPC diagnostic probe against `/home/bryan/projects/github/sase-org/sase/xprompts/reads.md`.
   Success means no diagnostics with codes `unknown_xprompt_frontmatter_field` or `unknown_xprompt` for
   `_article_search_agent`.

## Validation Plan

- Confirm command resolution:

  ```bash
  which -a sase-xprompt-lsp
  sase-xprompt-lsp --version
  sase lsp --version
  ```

- Run the focused Rust tests in the global `sase-core` checkout:

  ```bash
  cd /home/bryan/projects/github/sase-org/sase-core
  cargo test -p sase_core editor::diagnostics
  cargo test -p sase_xprompt_lsp diagnostics_for_uri_text_accepts_markdown_local_xprompts
  ```

- Run the live `sase lsp` JSON-RPC probe for `xprompts/reads.md`.

- Check the chezmoi source diff and apply target:

  ```bash
  git -C /home/bryan/.local/share/chezmoi diff -- home/bin/executable_install_sase_github
  chezmoi apply --force
  ```

## Expected Outcome

After this fix, `sase lsp` resolves to a freshly installed `sase-xprompt-lsp` from `PATH` instead of relying on
`target/debug`. Neovim should stop reporting both `reads.md` diagnostics after restarting the LSP client or Neovim.
