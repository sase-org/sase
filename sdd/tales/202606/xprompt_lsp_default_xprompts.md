---
create_time: 2026-06-10 09:25:13
status: done
prompt: sdd/prompts/202606/xprompt_lsp_default_xprompts.md
---
# Fix: xprompt LSP not attaching for `src/sase/default_xprompts/*.md` in neovim

## Problem

Opening `src/sase/default_xprompts/research_swarm.md` in neovim does not start/attach the `sase-xprompt-lsp` client, so
no xprompt completion, hover, or diagnostics are available in that buffer.

## Diagnosis (root cause)

This is **not** a chezmoi / user-config problem. The nvim config at
`~/.local/share/chezmoi/home/dot_config/nvim/lua/plugins/sase_nvim.lua` correctly enables the LSP
(`lsp = { enabled = true, native_completion = false }`); `allow_all_markdown` is intentionally left off so the LSP
doesn't attach to every markdown file.

The actual cause is markdown **path-eligibility gating that doesn't know about the `default_xprompts` directory**, in
two layers:

1. **sase-nvim client** — `lua/sase/lsp.lua` → `is_supported_markdown_path()` (lines ~152-159) only accepts markdown
   buffers whose path contains a literal `xprompts` or `.xprompts` path component, or temp prompt filenames
   (`sase_ace_prompt_*.md` / `sase_prompt_*.md`). `default_xprompts` is a different path component, so
   `supports_buffer()` returns false and the `FileType` autocmd never calls `vim.lsp.start()` for this file.

2. **sase-core server** — `crates/sase_xprompt_lsp/src/server.rs` → `markdown_uri_eligible()` (~line 1091) applies the
   identical `xprompts`/`.xprompts` component check, so even a manually attached client would mark the document
   ineligible and serve no features. Additionally, `should_invalidate_for_uri()` (~line 1121) uses the same gate, so
   edits to `default_xprompts/*.md` would not invalidate the server's xprompt catalog cache.

The inconsistency: the xprompt **catalog already treats `default_xprompts/` as a first-class xprompt source**. The
Python launcher (`src/sase/integrations/xprompt_lsp.py:135`) exports
`SASE_XPROMPT_DEFAULT_DIR=<package>/default_xprompts`, and `sase-core/crates/sase_core/src/xprompt_catalog.rs`
(~line 623) loads definitions from it. So these files define real xprompts (e.g. `#research_swarm`), but the editor
eligibility checks were never updated to allow editing them with LSP support. (Symptom also reproduces via
go-to-definition on a default xprompt: the jump lands in `default_xprompts/` where the LSP goes dark.)

## Plan

Per the Rust-core-backend-boundary rule, the shared eligibility behavior is fixed in `sase-core` first, then the thin
nvim client gate is kept in sync in `sase-nvim`. No changes are needed in the primary `sase` repo or in the chezmoi
repo.

### 1. sase-core (workspace `sase-core_10`) — server-side eligibility

- Add `default_xprompts` to the accepted path components in:
  - `markdown_uri_eligible()` in `crates/sase_xprompt_lsp/src/server.rs`
  - `should_invalidate_for_uri()` in the same file (so catalog cache invalidates on edits)
- Extend the existing unit tests (~line 1389, `document_eligible` assertions) with `default_xprompts` markdown cases for
  both eligibility and invalidation.
- Run the sase-core test/format/lint suite (`cargo test -p sase_xprompt_lsp`, fmt/clippy as configured).

### 2. sase-nvim (workspace `sase-nvim_10`) — client-side attach gate

- Add `has_path_component(path, "default_xprompts")` to `is_supported_markdown_path()` in `lua/sase/lsp.lua`.
- Add a matching assertion to `tests/lsp_config.lua` (alongside the existing `.xprompts`-markdown-supported case).
- Out of scope: `plugin/sase_yamlls.lua` schema globs (`*/xprompts/**/*.yml`) — `default_xprompts/` ships only `.md`
  prompt-part files today; no `.yml` workflows live there.

### 3. Verification

- Rebuild the LSP binary so the server-side change is live (the `sase lsp` launcher resolves `sase-xprompt-lsp` from
  PATH or `../sase-core/target/{debug,release}/`).
- Open `src/sase/default_xprompts/research_swarm.md` in nvim (with the local sase-nvim checkout on the runtimepath) and
  confirm `:LspInfo`/`:checkhealth` shows `sase-xprompt-lsp` attached and that `#xprompt` completion/hover works in the
  buffer.
- Run both repos' test suites.

### 4. Rollout note

Bryan's lazy.nvim spec tracks `sase-org/sase-nvim`, so after the sase-nvim change merges he needs a plugin update
(`:Lazy sync`), and the installed `sase-xprompt-lsp` binary must be rebuilt/updated for the server-side half to take
effect.
