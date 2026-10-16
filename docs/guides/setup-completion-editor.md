---
title: Set up shell completion and your editor
description: Complete sase commands with TAB and edit prompts with language assistance.
---

# Set up shell completion and your editor

This guide turns on `<TAB>` completion for `sase` commands and points your editor at
SASE's language server. It assumes SASE is installed; both steps are optional and
independent, so do either one alone.

## Before you start

You need to know your shell (`zsh`, `bash`, or `fish`) and, for the editor half, an
editor that speaks the Language Server Protocol over stdio.

## 1. Install shell completion

Detect the shell, write the loader, and verify the install:

```bash
sase completion install
```

The installer never edits rc files; it writes the completion script itself and prints a
`zstyle` snippet for `~/.zshrc` when one applies. Open a new shell afterward, because
completion scripts load once at shell startup. Confirm the install any time:

```bash
sase completion list
```

Never `eval "$(sase completion zsh)"` in an rc file: that pays a full `sase` startup on
every new shell. Write the script to a file instead, which is what the installer does.

## 2. Point your editor at the language server

Verify the wrapper, then configure the editor to launch `sase lsp` as a stdio language
server:

```bash
sase lsp --version
```

The wrapper prints the server version (for example `sase-macro-lsp 0.40.0`). In editor
configuration terms, the command is `sase` and the argument list is `["lsp"]`. The
server completes macro names, directives, models, and artifact references, and reports
hover, diagnostics, and jump-to-definition while editing prompts and macros.

## If it goes wrong

For completion, `sase doctor` runs the same install checks the installer uses; add
`-D -C completion.registration` to probe a real shell when a new shell still completes
nothing. For the editor, a server that cannot start usually needs a full SASE update or
the `SASE_MACRO_LSP_CMD` override in
[Editor integration](../reference/integrations/editor.md#troubleshooting).

## Related

- [Shell completion](../reference/integrations/completion.md) — loaders, value kinds,
  caching, and latency.
- [Editor integration](../reference/integrations/editor.md) — language-server features
  and the helper bridge.
