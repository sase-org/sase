---
title: Macro CLI and editor support
description: Macro command behavior and editor language-server features.
---

# Macro CLI and editor support

This page documents the macro CLI subcommands and editor language server.

## CLI

Usage, options, and arguments for every `sase macro` command are in the generated
[macro CLI reference](../cli/macro.md).

`sase macro list` returns JSON catalog entries for visible macros and workflows. Each
entry includes `insertion`, the authoritative reference text for clients, plus type,
kind, source, input definitions, tags, skill status, and a content preview. Standalone
workflows insert as `#!name`; macros and embeddable workflows insert as `#name`. Step
inputs are supplied by workflow execution and do not appear in the user input list.

For macro argument and input semantics, see [Arguments and typed inputs](arguments.md).

## Editor LSP

`sase lsp` starts the SASE macro language server over stdio for editor integrations. It
resolves the server command in this order:

1. `SASE_MACRO_LSP_CMD`, parsed as a shell-style command for development.
2. A `sase-macro-lsp` binary in the current Python environment's `bin/` directory.
3. `sase-macro-lsp` on `PATH`.
4. The newer debug or release `sase-macro-lsp` binary under a sibling `../sase-core`
   checkout.
5. `cargo run --manifest-path ../sase-core/Cargo.toml -p sase_macro_lsp --` when `cargo`
   is available and the sibling checkout has a `Cargo.toml`.

Examples:

```bash
sase lsp
sase lsp --version
SASE_MACRO_LSP_CMD='cargo run --manifest-path ../sase-core/Cargo.toml -p sase_macro_lsp --' sase lsp
```

Use `SASE_MACRO_LSP_CMD` for any non-default LSP command, including a custom binary that
should beat the managed venv copy. Full editable-install SASE updates reinstall the
server into the uv-tool venv when pulled `sase-core` commits change. `SASE_CORE_DIR` is
a `Justfile` build/install override, not part of `sase lsp` command resolution.

The LSP loads the supported macro catalog sources directly in Rust for completion,
hover, diagnostics, and definition requests. `sase lsp` exports the installed package
macro paths to the server so built-in Markdown prompts, YAML workflows, default config
prompts, project-local prompts, user config prompts, and memory prompts do not require a
Python helper subprocess on the completion path. The Python helper bridge remains stable
for mobile clients and as a compatibility fallback for sources the Rust loader cannot
discover.

When the editor advertises LSP `completionItem.snippetSupport`, the server also returns
SASE snippets as ordinary `CompletionItemKind.Snippet` entries after bare trigger words
such as `fix` or `review`. Snippet entries are loaded from the same registry as sase's
TUI: macros with `snippet` front matter plus user-defined `ace.snippets`, with
`ace.snippets` winning on trigger collisions. The registry also includes the generated
initial-capital aliases (`foo` → `Foo`), so a completion for `Foo` appears wherever
`foo` does. The editor does not need to shell out or parse SASE config to discover
snippets.

The Python helper operation `sase editor helper-bridge snippet-catalog` is the
authoritative snippet registry because it matches sase's TUI macro composition behavior.
The Rust server also has a native fallback for simple macro snippets and `ace.snippets`
so completion can degrade gracefully if the helper is unavailable. That fallback
intentionally skips macros that require complex Jinja or composition it cannot mirror
exactly; when the helper is available, its response is preferred.

The LSP also consumes the project's `glossary` memory web, authored as strand files
under `sase/memory/glossary/`; see [Memory Webs](../memory/memory.md#memory-webs). A leading VCS
workflow reference selects the glossary project for the document, otherwise the active
workspace project is used. Glossary phrases are emitted as standard `type` semantic
tokens, with the same case-insensitive, code-literal-skipping, longest-match scanner
sase's TUI uses. A phrase wrapped across one line break is emitted as one semantic token
per line. Derived plurals of terms and aliases are matched like configured aliases.
`sase-nvim` underlines those tokens by default through an overridable `SaseGlossaryTerm`
highlight group. Hover returns Markdown for the canonical term, aliases, project, and
source context, and go-to-definition targets the glossary strand file's definition
range. Explicit macro and artifact references keep precedence over glossary matches.
When the selected project is disabled, unknown, home, unreadable, or has an invalid
glossary, the server suppresses glossary semantics for that context instead of falling
back to another project's terms.

See the [editor integration guide](../integrations/editor.md) for setup, feature coverage, helper bridge
usage, and troubleshooting.

## Related

- [Macro reference](index.md)
- [Directive catalog](directives.md)
