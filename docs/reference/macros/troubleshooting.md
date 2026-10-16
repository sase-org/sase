---
title: Macro troubleshooting
description: Common macro expansion problems and ways to diagnose them.
---

# Macro troubleshooting

This page lists common macro expansion problems and how to diagnose them.

## Troubleshooting

If a launch prompt contains an unknown `#name` reference, SASE warns before launch and
passes the text through literally. This is non-blocking so prose hashtags can still be
used, but typos such as `#reviewww` are visible at `sase run`, `sase macro expand`, and
from the `sase tui` prompt bar.

If a definition file is malformed, run:

```bash
sase macro list
sase doctor -C config.macro_definitions
sase doctor -C config.macro_input_types
```

`sase macro list` and `config.macro_definitions` report `skipped: <file>: <error>` lines
for macro or workflow definitions that could not be loaded. `config.macro_input_types`
lists unknown type names, the deprecated `string` alias, and enum choice/default issues,
keeping the Rust suggestion text in each message. Warnings are `WARN`, not a load
failure.

If a launch fails with a directive migration error such as
`%wait(priority=...) has moved to %queue`, run:

```bash
sase doctor -C config.macro_directives
```

The check locates the definition file that still uses retired directive syntax. It scans
every loaded macro body and each workflow's `prompt_part` text for `%name` / `%n`,
`%tribe` / `%t`, `%time`, `%edit`, and `%wait(...)` / `%w(...)` calls that pass
`runners=`, `capacity=`, `priority=`, or `p=`, and prints each hit as
`<name> (<source>):<line>: <directive> — <migration hint>`. Code spans, fenced blocks,
and disabled regions are skipped. Findings are a `WARN`, so `sase doctor` still exits
`0` unless you add `-s/--strict`. Remember that a personal `~/sase/macros/<name>.md` or
project `sase/macros/` copy shadows a plugin or package macro of the same name, and
`sase macro show <name>` reveals which definition wins.

## Related

- [Macro reference](index.md)
- [Macro CLI and editor support](cli-and-editor.md)
