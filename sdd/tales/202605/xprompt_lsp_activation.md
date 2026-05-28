---
create_time: 2026-05-28 07:47:52
status: done
prompt: sdd/prompts/202605/xprompt_lsp_activation.md
---
# Plan: Restrict XPrompt LSP Activation

## Context

The xprompt LSP implementation lives in `../sase-core/crates/sase_xprompt_lsp`, while `../sase-nvim/lua/sase/lsp.lua`
currently starts that server for every `markdown`, `gitcommit`, `sase`, and `sase_prompt` buffer. That broad Markdown
activation makes ordinary prose files such as `sdd/research/202605/memory_system_prior_art.md` receive xprompt
completion, diagnostics, hover, and definition behavior even when they are not prompt or xprompt-definition files.

The server still needs to be available for SASE prompt-editing surfaces, including TUI `<ctrl+g>` temporary Markdown
files named like `sase_ace_prompt_*.md`, CLI prompt editor files named like `sase_prompt_*.md`, and Markdown files under
`xprompts/` or `.xprompts/`.

## Goals

1. Do not attach the Neovim xprompt LSP client to ordinary Markdown prose files by default.
2. Keep automatic LSP support for SASE prompt-editing Markdown buffers and xprompt definition Markdown files.
3. Add a Rust server-side document gate so manually configured or non-Neovim clients also receive no xprompt behavior
   for unsupported Markdown documents.
4. Preserve non-Markdown prompt-oriented filetypes (`gitcommit`, `sase`, `sase_prompt`) unless a test exposes a concrete
   reason to narrow them.
5. Keep the behavior configurable enough that users can opt into broader Markdown attachment if they already depend on
   it.

## Proposed Classification

A Markdown document is xprompt-LSP eligible when at least one of these is true:

- Its path is inside an `xprompts/` or `.xprompts/` directory.
- Its basename matches a SASE prompt-editor temporary file pattern, including `sase_ace_prompt_*.md` and
  `sase_prompt_*.md`.
- It is a known prompt buffer filetype such as `sase_prompt` rather than plain `markdown`.

Plain Markdown files elsewhere, including `sdd/research/**/*.md`, should be ineligible by default. I will avoid content
heuristics based on leading `#` because Markdown headings would create false positives.

## Implementation Steps

1. Add a small eligibility helper in `../sase-nvim/lua/sase/lsp.lua`.
   - Keep existing `filetypes` config for non-Markdown gating.
   - For `markdown`, require the path-based eligibility above unless a new config option explicitly allows all Markdown.
   - Use this helper from `supports_buffer()` and the `FileType` autocmd path so unsupported Markdown buffers do not
     start or attach the LSP.

2. Add tests in `../sase-nvim/tests/lsp_config.lua`.
   - Assert `xprompts/foo.md` and `.xprompts/foo.md` are supported.
   - Assert SASE temp prompts like `sase_ace_prompt_abc.md` and `sase_prompt_abc.md` are supported.
   - Assert `sdd/research/202605/memory_system_prior_art.md` is not supported.
   - Assert an opt-in config can preserve legacy "all Markdown" behavior.

3. Add a server-side document eligibility gate in `../sase-core/crates/sase_xprompt_lsp/src/server.rs`.
   - Track each opened document with text, language id, and eligibility instead of text alone.
   - For unsupported documents, store enough state to close/clear diagnostics cleanly, but return `None` or empty
     results for completion, hover, definition, and code action.
   - Publish empty diagnostics for unsupported documents.
   - Keep unit-facing helper methods such as `completion_for_text()` unchanged where possible, and gate the real LSP
     request path by URI/language/path.

4. Add Rust tests.
   - Unit-test the document eligibility helper with `xprompts/foo.md`, `.xprompts/foo.md`, `sase_ace_prompt_*.md`,
     `sase_prompt_*.md`, and `sdd/research/202605/memory_system_prior_art.md`.
   - Extend the JSON-RPC stdio test or add a targeted test showing unsupported Markdown produces no diagnostics and no
     completion.

5. Update documentation.
   - Adjust `../sase-nvim/README.md` so it no longer claims every Markdown buffer starts the server.
   - Mention the default Markdown narrowing and the opt-in legacy setting.

## Verification

- In `../sase-nvim`: run the Lua config test with headless Neovim, and run any smoke tests affected by the path gate.
- In `../sase-core`: run targeted xprompt LSP tests first, then `cargo fmt --all -- --check`,
  `cargo clippy --workspace --all-targets -- -D warnings`, and `cargo test --workspace` if time permits.
- In this Python repo: no code changes are planned here, so `just check` should not be required unless implementation
  reveals a necessary Python-side change.
