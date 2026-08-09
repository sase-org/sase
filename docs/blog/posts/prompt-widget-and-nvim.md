---
title: "[08] Where You Type — The Prompt Input Widget and sase-nvim"
date: 2026-05-22
draft: true
description: >-
  Where the operator actually types: a multiline Textual TextArea with completion,
  history, snippets, and a Vim mode in the TUI — and sase-nvim, the Neovim plugin that
  gives the same prompt language a richer editor.
categories:
  - Agentic Software Engineering
  - Plugins
slug: prompt-widget-and-nvim
links:
  - ACE TUI: ace.md
  - XPrompts: xprompt.md
  - Plugins: plugins.md
  - "[07] Driving SASE From Your Phone — Telegram as the Mobile Control Surface": blog/posts/telegram-mobile-agents.md
  - View on GitHub: https://github.com/sase-org/sase-nvim
---

# [08] Where You Type — The Prompt Input Widget and sase-nvim

Every agent run starts as a few characters typed into a box.
[\[02\]](xprompts-in-depth.md) covered the prompt _language_; this post covers the
surface you type that language into: the ACE prompt input widget, and the **sase-nvim**
plugin that lets the same language live inside Neovim with syntax highlighting,
completion, and go-to-definition.

<!-- more -->

[\[07\]](telegram-mobile-agents.md) moved the operator off the keyboard and into a chat
window. This post moves in the other direction — into the editor itself. Most agent
launches still happen at the keyboard, and most of the affordances that make those
launches fast (xprompt expansion, snippets, vim motions, an `EDITOR` handoff) live in
the prompt input widget.

## What The Widget Actually Is

The prompt input is a multiline Textual `TextArea` subclass — `PromptTextArea` in
`src/sase/ace/tui/widgets/prompt_text_area.py` — anchored at the bottom of the ACE TUI.
It auto-grows with wrapped content, shows line numbers once you spill onto a second
line, and renders Markdown syntax highlighting for headings, code fences, lists, bold,
and italics. The container around it, `prompt_input_bar.py`, owns the surrounding label,
the mode badge, and the messages the widget emits when you ask for an editor, history,
or a picker.

The widget operates in two modes:

- **INSERT** (default) is the editing surface. `Enter` submits; `Ctrl+J` inserts a
  newline, continues a containing hyphen bullet, and—with no selection—exits the list
  when the current line contains only optional leading spaces and an empty `- ` marker;
  `Ctrl+A` / `Ctrl+E` do readline-style line motion; `Escape` switches to NORMAL.
- **NORMAL** is a faithful slice of Vim. Motions (`h`/`j`/`k`/`l`, `w`/`e`/`b`, `f`/`t`,
  `0`/`$`, `gg`/`G`, `Ctrl+D`/`Ctrl+U`) and operators (`d`, `c`, `D`, `C`, `dd`, `cae`
  to wipe the buffer) accept count prefixes and write to the system clipboard. The
  border title flips to `[NORMAL]` and line numbers switch to relative numbering. `.`
  repeats the last mutation; `~` toggles case; `p` pastes.

The mode boundary matters because the same widget has to handle two different audiences:
someone dashing off `#mentor reorder` and pressing Enter, and someone editing a 30-line
plan-approval response with vim muscle memory. Both have to feel native.

## Completion: One Dispatcher, Plus Recursive Search

`Ctrl+T` is the main completion dispatcher, and what it does depends on what's under the
cursor:

| Cursor on…                              | Completion shows…                                                           |
| --------------------------------------- | --------------------------------------------------------------------------- |
| `#name` / `#!name` (xprompt reference)  | Matching xprompts with kind labels and visible typed inputs                 |
| `/skill` (slash skill)                  | The same catalog filtered to xprompts marked `skill: true`                  |
| `%directive` (e.g. `%m`)                | Directive list with aliases — `%m` accepts into `%model`, `%w` into `%wait` |
| Path-like token (`./`, `~/`, `/`, `@…`) | Filesystem entries; directories drill down on accept                        |
| Whitespace / empty prompt               | Recent-file history from `~/.sase/file_reference_history.json`              |

Path completion is rooted in the prompt when possible. Registered workspace-provider
refs and known-project refs such as `#git:<project>` or `#gh:<owner>/<repo>` can make
relative path candidates come from that project checkout instead of from whatever
directory launched ACE. For broader search, `Ctrl+R` opens a recursive fuzzy finder. A
path token like `src/alp` uses `src/` as the root and `alp` as the initial fuzzy query;
when the `Ctrl+T` panel is already open on a file/path candidate, the highlighted entry
seeds the recursive root.

Inside a known xprompt argument position, `Ctrl+T` flips to argument completion: `path`
inputs delegate to file completion, `bool` inputs offer `true` / `false`, and inside
`name(arg=…)` syntax the panel completes _missing_ named arguments so you can't
double-bind one. A separate `xprompt args` hint panel appears when an accepted xprompt
has required inputs — press `:` to switch to colon syntax, or `(` to expand a
named-argument snippet whose fields you tab through.

The same catalog drives the `#@` picker: type `#`, then `@`, and you get a modal browser
over every xprompt the project knows about. Inline xprompts insert as `#name`;
standalone workflows insert as `#!name`. Picker and `Ctrl+T` share insertion rules, so
the canonical form is the same whether you typed or browsed.

## Snippets, History, And The MRU Cycle

Beyond xprompts, the input bar supports plain text snippets configured in `ace.snippets`
in `sase.yml`. Type a trigger word, press `Tab`, and the trigger is replaced with the
template. Templates support `$1`, `$2` tabstops with `Tab` advancing through fields.
Snippets are intentionally lightweight — they are for boilerplate you keep retyping, not
for anything xprompts already do better.

Prompt history is the third reuse path. Press `Ctrl+K` from the input bar to open the
prompt history modal when the current prompt is a single line; that text pre-fills the
modal filter. `,.` opens the same modal from the main ACE UI. The modal loads prior
prompts by most recent use, with `PageDown` fetching older rows. `Enter` submits the
highlighted prompt directly; `Ctrl+G` loads it into your editor first; `Ctrl+I` loads it
into the input widget for tweaking (pressing `Tab` does the same thing). Normal launch
writes skip trivial one-token prompts (`y`, `ok`) so they do not clutter the list, while
failed-launch recovery can still preserve a short submitted prompt.

`Ctrl+P` and `Ctrl+N` cycle most-recently-used workspace references (such as `#git:foo`,
`#gh:org/repo`, and refs from other installed providers) through one ring with a
no-prefix stop: `Ctrl+P` moves toward older entries, and `Ctrl+N` moves toward newer
ones. They replace the first launchable workspace tag in the prompt or prepend a tag
when none is present. The history files behind this — monthly prompt-history shards
under `~/.sase/prompt_history/` and the file-reference history — use a sidecar lock plus
atomic tempfile replacement so concurrent agent launches do not truncate the shared
state.

## `Ctrl+G`: Handing Off To The Editor

`Ctrl+G` is the seam between the widget and everything outside it. Pressing it suspends
the TUI, writes the current buffer to a `sase_ace_prompt_*.md` file in the SASE tmpdir,
and launches `$EDITOR` (defaulting to `nvim`). For nvim, the widget passes
`-c "call cursor(row, col)"` so the editor opens at the same row and column the cursor
was on. When the editor exits, the file content is read back into the widget. If any
line of the result ends with a ` @` review marker, the widget strips the marker and
reloads it for a second editing pass; otherwise a single prompt submits immediately. If
`Ctrl+G` is used from an existing prompt stack, the whole stack is edited as
xprompt-style Markdown and returned to the bar instead of launching directly.

That handoff is why the next half of this post is about Neovim. The prompt input widget
is intentionally TUI-shaped — mode badge, single border, no syntax server, no
go-to-definition — and `Ctrl+G` is the escape hatch for everything the TUI deliberately
doesn't try to be.

## sase-nvim: The Neovim Side Of The Prompt Language

The [`sase-nvim`](https://github.com/sase-org/sase-nvim) plugin gives the same prompt
language a proper editor surface. It ships three things:

1. **Filetype detection and syntax highlighting** for
   `~/.sase/projects/<project>/<project>.sase` Patch files, with colors that match the
   `sase ace` rendering — field labels (`NAME:`, `STATUS:`, `HOOKS:`, `WORKSPACE_DIR:`),
   status values colored by lifecycle stage (WIP → Draft → Ready → Mailed → Submitted),
   inline process states (RUNNING/PASSED/FAILED/DEAD/KILLED), timestamps, URLs, file
   paths, and the suffix badges ACE uses for errors and running agents.
2. **A `<C-t>` completion dispatcher** that mirrors the widget's `Ctrl+T`: on `#token`
   it completes xprompts, on `/skill` it completes skills, on `%directive` it completes
   directives, on a path-like token it completes files, and on empty input it falls back
   to recent files. The keymap is opt-in —
   `require("sase").setup({ complete = { keymap = true } })` — so the plugin doesn't
   shadow your existing `<C-t>` binding unless you ask.
3. **A YAML language-server registration** that points `yamlls` at SASE's schemas for
   `sase.yml` and xprompt workflow files, so config edits get inline validation and
   hover help.

The completion backend has two modes. When the SASE xprompt LSP is reachable —
`sase lsp` or `sase-xprompt-lsp` — the plugin attaches an LSP client and gets
server-driven completion, go-to-definition on `#foo` references, and snippet completion
sourced from the same registry the ACE widget uses (so xprompts marked `snippet: true`
and `ace.snippets` entries appear in both places). When the LSP isn't available, the
plugin falls back to legacy pickers backed by `sase xprompt list` and a local
file-history reader. The behavior the user sees stays the same; only the source of truth
shifts.

The `#@` insert-mode trigger from the ACE widget is mirrored too. Typing `#` then `@` in
a Neovim buffer opens an xprompt picker modal driven by the same catalog; the
`:SaseXPrompts` command opens it manually. `<C-d>` in the recent-files picker removes
the highlighted entry from `~/.sase/file_reference_history.json` — the same on-disk
store the widget uses, edited from the other side.

## Two Surfaces, One Language

The throughline is that the prompt language is the contract, and the editing surface is
interchangeable. ACE's input widget is optimized for short, fast, in-TUI launches;
sase-nvim is optimized for long prompts, multi-file context, and the muscle memory of an
editor you already use for code. Both speak the same xprompt names, the same directive
aliases, the same slash-skill catalog, the same recent-files store. A prompt drafted in
nvim and saved is the prompt that hits the agent; a prompt typed in the widget and sent
via `Ctrl+G` to nvim and back is the same prompt either way.

That's the point of having a plugin in the first place. The widget doesn't try to grow
into an editor, and Neovim doesn't try to grow a TUI panel — `Ctrl+G` and the shared
catalog make them the same input system from two different front doors.

## What To Read Next

- [Prompt input widget reference](../../ace.md#prompt-input-widget) — the full keymap
  table, completion semantics, and the snippet expansion grammar.
- [sase-nvim on GitHub](https://github.com/sase-org/sase-nvim) — installation, the full
  `<C-t>` dispatcher table, LSP configuration, and the YAML schema registration.
- [XPrompts reference](../../xprompt.md) — the language the widget and the plugin both
  speak.
- [ACE TUI guide](../../ace.md) — the rest of the TUI the prompt widget sits inside.
