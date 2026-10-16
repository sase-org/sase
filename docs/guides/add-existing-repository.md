---
title: Add an existing repository
description: Register a repository you already have as a SASE project and initialize it.
---

# Add an existing repository

This guide registers a repository you already have as a SASE project so agents can work
in it. It assumes the repository exists locally with a remote; if that is not your
situation, create the Git repository first and then come back.

## Before you start

You need SASE installed and the repository checkout on this machine. If SASE is not set
up yet, follow [Install and set up SASE](../start/install.md).

## 1. Preview the registration

Show the read-only plan without writing anything, and confirm it names the project you
expect:

```bash
sase project add <repository> --check
```

`<repository>` is your existing repository reference, for example its local path.
Previewing is free for agents and people alike; the actual setup step needs a person to
confirm it.

## 2. Register the project

Register the repository as an enabled SASE project:

```bash
sase project add <repository>
```

Setup can write the repository's management file, commit it, and push the default
branch. When setup succeeds in a terminal, it can offer to initialize the project
directly.

## 3. Initialize the project

Preview what initialization would change, then apply it:

```bash
sase init -p <name> --check
sase init -p <name> --yes
```

Initialization walks the config, machine, memory, repository, service, and skills steps
in order. Confirm everything is current:

```bash
sase init --check
```

SASE reports that it is initialized and no steps need to run.

## If it goes wrong

Run the read-only checks in
[Diagnose problems with sase doctor](diagnose-with-doctor.md) and follow the step they
point at.

## Related

- [Initialization](../init.md) — every setup command, flag, and batch mode.
- [Agents, sessions, and workspaces](../concepts/agents.md) — how the project gives
  agents isolated checkouts to work in.
