---
title: "[04] Beads and SDD — Planning Multi-Agent Work That Actually Lands"
date: 2026-05-16
draft: true
description: >-
  Orchestration only matters if you can split work into pieces with a real ordering. Beads and Spec-Driven Development
  are how SASE files that work and schedules it.
categories:
  - Agentic Software Engineering
  - Planning
slug: beads-and-sdd
links:
  - Spec-Driven Development: sdd.md
  - Beads: beads.md
  - "[03] AXE — The Background Daemon That Keeps Agent Work Moving": blog/posts/axe-background-daemon.md
  - View on GitHub: https://github.com/sase-org/sase
---

# [04] Beads and SDD — Planning Multi-Agent Work That Actually Lands

> Terminology note (July 2026): the “companion repos” named in this historical post are now called **sidecar repos**.

Orchestration only matters if you can split work into pieces with a real ordering. Beads and Spec-Driven Development
(SDD) are the two pieces of SASE that file plans on disk and turn them into work that an agent fleet can execute.

<!-- more -->

[\[03\]](axe-background-daemon.md) explained how AXE keeps individual agents moving in the background. This post is
about what feeds it: how plans become durable artifacts, how those plans turn into ordered work units, and how a single
command turns an epic into a multi-agent run with real dependency ordering.

## SDD in One Minute

Spec-Driven Development persists the intent behind agent work. When an agent submits a plan for approval, SDD captures
both the **expanded prompt snapshot** (every `#xprompt` resolved, every `%directive` stripped) and the **approved plan**
as first-class artifacts on disk. The two files cross-reference each other via top-of-body `PLAN` and `PROMPT` Markdown
bullets, and `sase plan links validate` checks that the link graph is intact.

Two plan tiers share one canonical plans root:

- **Tales** — ordinary implementation plans at `<plans-root>/{YYYYMM}/{name}.md` with `tier: tale`.
- **Epics** — executable multi-phase plans at the same path shape with `tier: epic`.

Storage follows workspace-provider policy. Built-in bare-git projects use in-tree `sdd/`; newly initialized managed
GitHub projects use role-specific sidecars such as `--plans`, `--research`, and, in schema 3, `--beads`; unmigrated
GitHub projects retain their `.sase/sdd/` clone; providerless projects use the primary workspace's local `.sase/sdd/`
store. A positive sidecar-store record preserves the resolved GitHub layout for offline use.

`sase plan search -k epic` lists every epic; `sase plan links validate` checks the prompt/plan link graph;
`sase repo init` materializes provider-owned storage and refreshes the generated READMEs and directory-map asset. The
reference is in [`sdd.md`](../../sdd.md).

## Beads Are the Work Unit

A **bead** is a git-portable issue record backed by a canonical append-only event store. The general lifecycle is `open`
→ `in_progress` → `closed`, with machine-managed `claimed` and a task-only `ready` status. Beads have dependency edges
and can carry artifact references and a model annotation (`-m/--model`). Plan beads also carry a plan reference (the
`design` field) and a tier (`plan` or `epic`). Storage lives under the resolved SDD store: `events/**` is the source of
truth, `issues.jsonl` is a generated compatibility projection, and `beads.db` is a gitignored compatibility cache. Fresh
clones read the tracked event store directly and can rebuild the mirrors on demand.

Three issue types:

- **Plan** beads — plan-like containers. ID format `{prefix}-{counter}`.
- **Phase** beads — executable children inside an epic. ID format `{parent_id}.{N}` (so `myapp-7.1`, `myapp-7.2`, …).
- **Task** beads — flat, independent follow-ups with no parent, plan tier, or ChangeSpec metadata.

Epic-tier plan beads hand off to a phase-and-land run through `sase bead work`; a standalone task bead hands off to one
deterministically named worker through the same command.

## Ready Versus Blocked

Task readiness is an explicit human-triage state:

```bash
sase bead create --type task --title "Follow up"
sase bead update <task-id> --status ready
sase bead ready              # ready task beads whose deps are all closed
sase bead blocked            # beads with active dependencies
sase bead show <task-id>     # one bead in detail
```

AXE scans stored-ready tasks every five minutes and creates a `TaskTriage` notification with **Launch** and **Close**
branches. The command and the scheduled scan currently differ in one important way: `sase bead ready` filters out
blocked tasks, while the AXE scan looks only at stored status and can create a triage gate for a blocked ready task.
Direct `sase bead work <task-id>` likewise accepts open, ready, or recoverable in-progress tasks without rejecting
active blockers.

## `sase bead work <epic-id>`: Multi-Agent Execution

The most useful single command in this layer turns an epic-tier plan into actual work. Given an `<epic-id>`, it:

1. Validates the bead resolves to a `plan` issue with `tier=epic`.
2. Previews deterministic-name reuse for `<epic-id>.1`, `<epic-id>.2`, and `<epic-id>.land`; after confirmation, it
   removes prior owners (including live ones) or aborts before changing bead state if cleanup cannot finish.
3. Flips the epic plan bead's `is_ready_to_work` flag to `True`.
4. Builds a **Kahn-wave schedule** from the epic's open phase children, respecting dependencies.
5. Preassigns each scheduled phase bead and the epic itself — `status=in_progress`, with deterministic phase and land
   agent assignees — then commits the complete graph as one pre-spawn checkpoint. Detached bead stores synchronously
   publish that checkpoint before work can start.
6. Hands a single `---`-separated multi-prompt to the agent launcher: one segment per phase, plus a final land segment.
   Each phase dependency becomes both an agent-success wait and a bead-closure wait; the land agent waits for every
   authored phase bead.

Because every segment uses `%id(!<agent_name>, bead=<bead-id>)` (force-reuse) and bare `%auto`, `sase bead work` is safe
to retry after a killed or failed run while still auto-approving submitted phase and landing plans. Those agents may
author a tale or an epic as needed; the plan's authored `tier` selects the automatic follow-up path. AXE's `wait_checks`
chop is what unblocks each phase only after its blocker has both a successful `done.json` and a closed bead. Failed,
killed, or finished-but-unclosed phases keep dependents and the land agent parked — there is no fail-open.

For a task bead, the same command renders one prompt, checkpoints the task as `in_progress` with assignee `<task-id>`,
and then launches that deterministic worker. An explicit task model wins; otherwise a stored size selects the
corresponding size-specific phase-worker alias, while a legacy task without size uses the small route. Large and xlarge
tasks receive the same automatic `#plan` handoff as equivalently sized phases.

Agents use `/sase_new_task` before filing discovered work. The skill corroborates a semantic duplicate with
`sase bead +1`, records work caused by an in-progress epic on that epic, and creates a new task only when neither case
applies. Every newly created task has an explicit size; sizeless support is retained only for legacy records.

## The Promote-From-Chat Discipline

Agents propose plans; humans (or distillation workflows) promote them into SDD. The reason: keeping raw transcripts out
of the canonical planning artifact. The agent's chat is episodic evidence. The plan that lands on disk should be
something a reviewer can trust six months later without needing to re-read the conversation that produced it.

In practice, SDD enforces this shape by writing the plan only when it is submitted via `sase plan propose` (which
touches `~/.sase/.ace_refresh_pulse` so any running ACE TUI flips the agent into the `PLAN` status immediately) and by
appending Q&A exchanges, when present, as a single merged `### Questions and Answers` section with monotonic numbering
across rounds. The proposal can then be promoted from ACE or with `sase plan approve <id-prefix> --kind tale|epic`; the
promoted plan is what links to the bead, while the chat stays as a `CHAT:` drawer on the eventual commit.

## Workspace Behavior

SDD plan artifacts are shared through the normal project workflow. With in-tree provider policy, bead state is
deliberately checkout-local: `sase bead` reads and mutates the `sdd/beads/` event store in the checkout where the
command runs. An agent running in `myproject_3` sees `myproject_3/sdd/beads/`, not a merged view of `myproject/`,
`myproject_2/`, and `myproject_3/`. Providerless local storage resolves numbered checkouts back to the primary
workspace's `.sase/sdd/beads/` store. With a legacy single companion, each numbered checkout uses its own `.sase/sdd/`
clone. With schema-3 split storage, it uses the root of its auto-cloned `--beads` sidecar; schema-2 records retain
`beads/` in the `--plans` sidecar.

That keeps the source of truth inspectable and unsurprising. For in-tree work, bead state moves between checkouts
through the same VCS sync path as code and SDD files, and ID allocation uses the active checkout's local `config.json`
and canonical event state. Providerless local stores are shared through the primary workspace; provider sidecars
synchronize through the clone in the active workspace.

## What To Read Next

- [Spec-Driven Development](../../sdd.md) — full reference for tales, epics, research, storage modes, bead integration.
- [Beads](../../beads.md) — every `sase bead` subcommand, the data model, and the current-checkout source-of-truth rule.
- [\[05\] Commit Workflows — The Pluggable Path From Diff to PR](commit-workflows-plugins.md) — how the work that
  `sase bead work` schedules eventually lands as commits, proposals, or PRs.
