---
create_time: 2026-06-04 19:54:05
status: done
---
# Plan: Launch Three Inbox Research Swarms

## Context

Bryan captured eight inbox items from Google Keep:

- Use xprompt workflows to define "Agent Family Types" using xprompt tags.
- Create `/sase_run` xprompt skill and add a way for users to approve sase agent launches.
- Figure out how to use Apollo to allow SASE to run agents on remote machines.
- Migrate `eat.md` to `eat/` and `eat.base`; Rush Bowl sucks.
- Start copying Obsidian PDF files over to Athena somehow.
- Project aliases solve the GitHub repo duplication issue.
- Refresh memory on Dataview.
- Add support for defining tasks in Highlights app notes.

The request is not to explore all eight independently. The right move is to launch three focused `research_swarm` daemon
agents, each seeded with a cluster of related notes and an explicit expected output. Each launched prompt should use the
GitHub VCS xprompt workflow form, e.g. `#gh:bob #research_swarm:: ...` or `#gh:sase #research_swarm:: ...`, then run
through `sase run -d`.

## Topic 1: SASE Agent Launch UX and Agent Family Types

Cluster:

- Agent Family Types via xprompt tags.
- `/sase_run` xprompt skill.
- User approval for sase agent launches.

Launch this against the `sase` project using `#gh:sase`. Ask the swarm to research the current xprompt model, skill
model, daemon launch flow, Telegram/prompt approval points, and existing family/group metadata. The output should be a
design memo for a safer and more expressive agent-launch interface, including:

- How xprompt tags could define agent family types without creating hidden coupling.
- Whether `/sase_run` belongs as a skill, xprompt, command wrapper, or some combination.
- Where approval should happen for direct `sase run -d`, Telegram, multi-agent xprompts, and nested workflow fanout.
- A proposed implementation sequence and risks.

## Topic 2: Bob/Obsidian Knowledge Workflow: PDFs, Dataview, Highlights Tasks

Cluster:

- Copy Obsidian PDF files to Athena.
- Refresh memory on Dataview.
- Define tasks in Highlights app notes.
- Related context from the recent Highlights reference-note sync work.

Launch this against the `bob` project using `#gh:bob`. The swarm should treat `~/bob/` as the Obsidian vault and use
read-only inspection where possible. It should connect the Dataview task model, PDF/reference-note storage, Highlights
sidecar/annotation outputs, and Athena/headless sync constraints. The output should be a practical roadmap for turning
PDF reading/annotation into actionable Obsidian tasks and searchable reference notes, including:

- How PDF assets should move or mirror to Athena without corrupting Obsidian Sync expectations.
- How Dataview metadata should represent tasks captured from Highlights notes.
- How this should relate to existing `bob-cli` Highlights sync work.
- What should be implemented first versus deferred.

## Topic 3: SASE Workspace Topology: Apollo Remote Agents and Project Aliases

Cluster:

- Use Apollo to allow SASE to run agents on remote machines.
- Project aliases solve the GitHub repo duplication issue.

Launch this against the `sase` project using `#gh:sase`. The swarm should research current workspace-provider,
project-resolution, GitHub VCS workflow, and agent-launch assumptions, then produce a design memo for remote-capable
agent execution with stable project identity. The output should include:

- What "remote machine" means for SASE: workspace allocation, command execution, logs, artifacts, credentials, and
  synchronization.
- How project aliases should prevent duplicate GitHub repo identities across local paths, bare repos, and remote hosts.
- How Apollo should integrate with or wrap existing workspace providers.
- A staged architecture that can be tested locally before true remote execution.

## Execution

Before launches, verify the prompt syntax by expanding one representative `#research_swarm:: ...` prompt. Then start
three detached agents with `sase run -d`, one per topic. Use careful shell quoting so multiline prompts are passed as a
single argument.

After launch, confirm that the agents are visible with the SASE agent status command or equivalent, and report the three
top-level prompt topics back to Bryan.
