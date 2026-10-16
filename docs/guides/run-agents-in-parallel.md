---
title: Run agents in parallel
description:
  Split independent work across agents and follow each run from the Agents tab.
---

# Run agents in parallel

Use a prompt stack to give several independent tasks to agents at once. Each agent gets
its own workspace, so its edits stay separate while it works.

## Before you start

You need a project ready to launch agents and tasks that can proceed independently. If
the tasks depend on one another or edit the same files, split them into sequential work
instead.

## 1. Write one task per agent

Open SASE's TUI and write the first task in the prompt bar. Give it one outcome, a clear
scope, and a way to tell when it is done. Keep the task small enough for one agent to
finish and review.

## 2. Add a pane for each task

Press `Ctrl+G -` in the prompt bar to add an empty pane. Write the next task there, then
repeat for each independent task. Keep each pane focused on one outcome and give agents
different files or areas to own when possible.

## 3. Launch the whole stack

Press `Enter` to open the submission chooser, then press `a` to launch all panes. SASE
launches one agent for each pane. Each run appears as its own row on the Agents tab.

## 4. Follow each run

Watch the Agents tab for progress and completion. Open each run to read its prompt,
response, and artifacts. An agent's workspace is separate from the others; review the
results before combining changes that touch the same area.

## If it goes wrong

If one task needs another agent's result first, launch it after that result is ready and
[hand the result to the follow-up agent](hand-a-result-to-another-agent.md). For prompt
stack controls, see [SASE's TUI](../reference/tui/prompt-stacks.md#prompt-stacks-1).

## Related

- [Agents, sessions, and workspaces](../concepts/agents.md) — how parallel runs stay
  isolated.
- [Prompt stacks](../reference/tui/prompt-stacks.md#prompt-stacks-1) — the prompt stack
  keybindings and behavior.
