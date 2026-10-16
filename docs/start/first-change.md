---
title: Make and review a change
description:
  Ask an agent for one small edit in SASE's demo workspace and inspect the resulting
  diff.
search:
  boost: 2
---

# Make and review a change

This tutorial asks an agent to make one small edit in the demo workspace and shows you
how to review it.

## Before you start

You need to have completed [Run your first agent](first-run.md) and have an
authenticated provider available.

## 1. Ask for one small edit

Before starting the run, know what happens when the agent submits its final declaration:
SASE's default host finalizer commits the change and pushes it to the `+home` project's
remote. That remote is a local bare repository, so this does not publish your change to
a public hosting service.

Ask the agent to create one file with one line:

```bash
sase run "+home create welcome.txt containing exactly this line: My first SASE change. Do not edit other files."
```

The agent works in an isolated workspace. Its prompt asks for one file, but workspace
isolation does not enforce those instructions. Review the result before using the same
workflow with one of your own projects.

## 2. Inspect the change

Open the terminal interface:

<!-- tutorial-test: skip opens an interactive terminal interface -->

```bash
sase tui
```

On the Agents tab, find the run that created `welcome.txt` and wait for it to finish.
Open the Commits pane in Artifacts, select the new commit, and press Enter to read its
message and diff.

## You have made and reviewed a change

You have seen the file change and the commit that records it in SASE's demo project.

## Next

- [Add an existing repository](../guides/add-existing-repository.md)
- [Explore how SASE works](../concepts/index.md)
- [Learn about workspaces](../reference/agents/index.md)
