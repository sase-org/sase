---
title: Run your first agent
description: Launch a read-only request in SASE's demo workspace and inspect the result.
search:
  boost: 2
---

# Run your first agent

This tutorial launches one agent in SASE's demo workspace and shows where to find its
result.

## Before you start

You need SASE installed and one supported agent CLI installed and authenticated. If you
have not set those up, follow [Install and set up SASE](install.md).

## 1. Confirm SASE is ready

Check that the command is available:

<!-- tutorial-test: expect "sase" -->

```bash
sase version
```

SASE prints its version and the version of its core extension.

## 2. Ask an agent to inspect the demo workspace

The `+home` project is SASE's managed demo workspace. It is separate from the directory
where you run this command, so the agent works in the demo project rather than in the
folder open in your shell. SASE prepares the demo project the first time you use it.

This request asks the agent to list the top-level files without changing them. Prompt
instructions describe the task but do not enforce what an agent can do, so read the
result before asking an agent to edit anything.

```bash
sase run "+home list the top-level files in this demo workspace; do not change files"
```

SASE starts the run and records its prompt and status. The command returns while the
agent works, so you can continue using the terminal. The run appears on the Agents tab
as soon as SASE records it.

## 3. Inspect the run

Open SASE's terminal interface:

<!-- tutorial-test: skip opens an interactive terminal interface -->

```bash
sase tui
```

The interface opens on the Agents tab. Find the row whose prompt asks to list the demo
workspace's files. The row shows the prompt and current status; select it to read the
run details. Wait until the run is done, then read the agent's response in its
transcript. The response is the result of this request, and the recorded prompt and
status stay with the run after it finishes.

## You have launched and inspected a SASE run

You have asked an agent to inspect the demo workspace and found its prompt, status, and
result.

## Next

- [Make and review a change](first-change.md)
- [Learn about agents and workspaces](../agent_sessions.md)
