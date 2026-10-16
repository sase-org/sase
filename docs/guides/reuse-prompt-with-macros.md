---
title: Reuse a prompt with macros
description: Save a useful prompt as a named macro and use it in later agent runs.
---

# Reuse a prompt with macros

Save a useful prompt as a macro when you want to start future tasks with the same
instructions.

## Before you start

You need a prompt that has worked at least once and is useful in more than one run.
Remove details that belong only to one task, and make changing values easy to identify.

## 1. Load the prompt you want to reuse

Open the prompt in SASE's TUI. For a prompt that has already run, find it in History and
load it into the prompt bar as a draft. For an unsent draft, keep it in the prompt bar.
See [Find and replay an old prompt](find-and-replay-prompt.md) for the History steps.

## 2. Save it as a macro

In the prompt bar, use `Ctrl+G X` to open the save panel. Choose a project location when
the prompt belongs to one repository, or a home location when you want it across
projects. Give it a short name that describes what it does and save it.

## 3. Use the macro in a prompt

Type `#<name>` where you want the saved instructions to appear, replacing `<name>` with
the name you chose. Add the details for this run, then review the prompt before
launching. Macro arguments and expansion rules are listed in the
[Macro reference](../reference/macros/index.md).

## If it goes wrong

If the macro does not appear in completion, check the location where you saved it and
that the prompt uses its exact name. Browse the macro catalog to see the discovered name
and preview its definition.

## Related

- [Macros](../reference/macros/index.md) — macro names, inputs, and expansion behavior.
- [Prompts, macros, and workflows](../concepts/prompts.md) — when to use a macro.
