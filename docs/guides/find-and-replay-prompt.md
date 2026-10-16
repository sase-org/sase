---
title: Find and replay an old prompt
description: Search prompt history, inspect a past prompt, and launch it again safely.
---

# Find and replay an old prompt

Search prompt history to find a previous task, inspect it, and launch it again or edit
it first.

## Before you start

You need a prompt that SASE recorded from an earlier run. Check its project and
workspace target before you replay it so the new run goes to the right place.

## 1. Open prompt history

In SASE's TUI, press `Ctrl+K` in the prompt bar or `,.` from a main tab to open History.
Search for a distinctive phrase from the prompt. Use the project filter when several
projects have similar prompts. Press `Ctrl+J` to load older history when the prompt is
not in the current page.

## 2. Inspect the prompt before launching

Select a history row to read its full prompt. Press `Tab` to load it into the prompt bar
as a draft, then update its workspace target or task details if they have changed. Press
`Enter` and confirm the launch action when the prompt is ready.

Pressing `Enter` on a history row submits it directly. Load it with `Tab` first when you
want to review or edit it before it runs.

## 3. Use the shell when you prefer a command

Run `sase prompt list` to see recent prompts, then use `sase prompt run <id> -e` to open
one in an editor before launching. The
[prompt reference](../reference/prompt-history.md) lists search, filter, replay, and
cancellation options.

## If it goes wrong

Cancelled prompts are hidden from the normal History list. Show cancelled prompts in the
overlay with `Ctrl+X`, or use the cancelled filter in the shell when you are recovering
an unlaunched prompt.

## Related

- [Prompt history](../reference/prompt-history.md) — shell commands and prompt-history
  fields.
- [Prompts overlay](../reference/tui/prompts-overlay.md#prompt-history-modal) — TUI
  History keybindings and filters.
- [Prompts, macros, and workflows](../concepts/prompts.md) — how prompts fit with
  reusable macros.
