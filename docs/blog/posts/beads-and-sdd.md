---
title: "Post 5: Beads and SDD — Planning Multi-Agent Work That Actually Lands"
date: 2026-05-16
description: >-
  Orchestration only matters if you can split work into pieces with a real ordering. Beads and Spec-Driven Development
  are how SASE files that work and schedules it.
categories:
  - Agentic Software Engineering
  - Planning
slug: beads-and-sdd
links:
  - Agentic Software Engineering Series: series/agentic-software-engineering.md
  - Spec-Driven Development: sdd.md
  - Beads: beads.md
  - "Post 4: AXE — The Background Daemon That Keeps Agent Work Moving": blog/posts/axe-background-daemon.md
  - View on GitHub: https://github.com/sase-org/sase
---

# Post 5: Beads and SDD — Planning Multi-Agent Work That Actually Lands

Orchestration only matters if you can split work into pieces with a real ordering. Beads and Spec-Driven Development
(SDD) are the two pieces of SASE that file plans on disk and turn them into work that an agent fleet can execute.

<!-- more -->

[Post 4](axe-background-daemon.md) explained how AXE keeps individual agents moving in the background. This post is
about what feeds it: how plans become durable artifacts, how those plans turn into ordered work units, and how a single
command turns an epic into a multi-agent run with real dependency ordering.

## SDD in One Minute

Spec-Driven Development persists the intent behind agent work. When an agent submits a plan for approval, SDD captures
both the **expanded prompt snapshot** (every `#xprompt` resolved, every `%directive` stripped) and the **approved plan**
as first-class artifacts on disk. The two files cross-reference each other via `prompt:` and `plan:` frontmatter fields,
and `sase sdd validate` checks that the link graph is intact.

Three plan tiers, three on-disk locations:

- **Tales** — ordinary implementation plans, at `sdd/tales/{YYYYMM}/{name}.md`.
- **Epics** — executable multi-phase plans, at `sdd/epics/{YYYYMM}/{name}.md`.
- **Legends** — higher-level coordination plans that own linked epics, at `sdd/legends/{YYYYMM}/{name}.md`.

There are two storage modes. The default (`sdd.version_controlled: false`) keeps everything in a standalone git repo
inside the primary workspace at `.sase/sdd/`, so SDD history stays separate from project history. With
`sdd.version_controlled: true`, the same trees live at `sdd/` at the project root and ship with code commits. Pick the
mode that matches how you want the audit trail reviewed.

`sase sdd list -k epics` lists every epic; `sase sdd validate` checks the prompt/plan link graph; `sase sdd init`
refreshes the generated READMEs and the directory-map asset. The reference is in [`sdd.md`](../../sdd.md).

## Beads Are the Work Unit

A **bead** is a git-portable, SQLite-backed, JSONL-shadowed issue record. Status moves through `open` → `in_progress` →
`closed`. Beads have dependency edges. Each one can carry a plan reference (the `design` field), a tier (`plan`, `epic`,
or `legend`), and a model annotation (`-m/--model`). Storage is a SQLite cache plus a `issues.jsonl` text shadow — the
cache is gitignored, the JSONL is committed. A fresh clone rebuilds the database from JSONL on first access; manual
JSONL edits are picked up the same way.

Two issue types:

- **Plan** beads — plan-like containers. ID format `{prefix}-{counter}`.
- **Phase** beads — executable tasks inside an epic. ID format `{parent_id}.{N}` (so `myapp-7.1`, `myapp-7.2`, …).

Plan-tier beads can hand off to `sase bead work`; phase-tier beads carry the actual units of executable work.

## Ready Versus Blocked

Once dependencies are real, the queue tells you what to start next:

```bash
sase bead ready              # open beads whose deps are all closed
sase bead blocked            # everything else
sase bead show <bead-id>     # one bead in detail
```

That is the daily working surface. You stop reconstructing "what should I do now?" from chat scrollback and start
reading it from a queue that was already correct.

## `sase bead work <epic-id>`: Multi-Agent Execution

The most useful single command in this layer turns an epic-tier plan into actual work. Given an `<epic-id>`, it:

1. Validates the bead resolves to a `plan` issue with `tier=epic`.
2. Scans the live agent registry for name collisions (`<epic-id>.1`, `<epic-id>.2`, `<epic-id>` for the land agent) and
   refuses to launch when one exists, listing the offending artifact directories so you can wipe them first. `-n` /
   `--dry-run` downgrades this to a warning.
3. Flips the epic plan bead's `is_ready_to_work` flag to `True`.
4. Builds a **Kahn-wave schedule** from the epic's open phase children, respecting dependencies.
5. Pre-claims each phase bead — `status=in_progress`, `assignee=<phase_bead_id>`.
6. Hands a single `---`-separated multi-prompt to the agent launcher: one segment per phase, plus a final segment for
   the land agent. Phase dependencies become `%wait` directives on blocker phase-agent names; the land agent waits on
   every launched phase agent.

Because every segment uses `%name:!<agent_name>` (force-reuse) and `%approve` (self-approve), `sase bead work` is safe
to retry after a killed or failed run. AXE's `wait_checks` chop is what unblocks each phase the moment its blockers have
`done.json` outcomes of `completed`. Failed or killed phases keep the land agent parked until that phase name retries
successfully — there is no fail-open.

Legend-tier work is similar in shape but plans rather than executes: `sase bead work <legend-id>` launches one
epic-planning agent per stored `epic_count` (sequentially via `%wait` chaining), then a final `land_legend` agent. Those
epic-planning agents create epic plans through the normal plan-approval flow; the linked epic and its phase beads are
created later by the `bd/new_epic` automation.

## The Promote-From-Chat Discipline

Agents propose plans; humans (or distillation workflows) promote them into SDD. The reason: keeping raw transcripts out
of the canonical planning artifact. The agent's chat is episodic evidence. The plan that lands on disk should be
something a reviewer can trust six months later without needing to re-read the conversation that produced it.

In practice, SDD enforces this shape by writing the plan only when it is submitted via `sase plan` (which touches
`~/.sase/.ace_refresh_pulse` so any running ACE TUI flips the agent into the `PLANNING` status immediately) and by
appending Q&A exchanges, when present, as a single merged `### Questions and Answers` section with monotonic numbering
across rounds. The promoted plan is what links to the bead; the chat stays as a `CHAT:` drawer on the eventual commit.

## Multi-Workspace Behavior

SDD always writes to the **primary workspace** (workspace 1). An agent running in `sase_3` resolves the primary by
stripping the `_3` suffix and writes there. Beads are the same: writes go to the primary workspace, reads aggregate
across every `myproject`, `myproject_2`, `myproject_3` clone via the Rust merged workspace view. For duplicate IDs
across workspaces, the version with the most recent `updated_at` wins.

That is what lets several agents work in sibling workspaces without stepping on each other's bead writes. A phase agent
in `myproject_4` closes its own phase bead in the primary store; the next phase agent's `%wait` sees that close through
the merged view; the land agent in `myproject_1` sees every closed phase. ID allocation also scans JSONL stores from all
discovered workspace variants before assigning the next ID, so two sibling workspaces never collide.

## What To Read Next

- [Spec-Driven Development](../../sdd.md) — full reference for tales, epics, legends, myths, research, storage modes,
  bead integration.
- [Beads](../../beads.md) — every `sase bead` subcommand, the data model, the Rust-backed merged read view,
  multi-workspace specifics.
- [Post 6: Commit Workflows — The Pluggable Path From Diff to PR](commit-workflows-plugins.md) — how the work that
  `sase bead work` schedules eventually lands as commits, proposals, or PRs.

## Series Navigation

This is Post 5 of the [Agentic Software Engineering series](../../series/agentic-software-engineering.md).

- Previous: [Post 4: AXE — The Background Daemon That Keeps Agent Work Moving](axe-background-daemon.md).
- Next: [Post 6: Commit Workflows — The Pluggable Path From Diff to PR](commit-workflows-plugins.md).
- Continue reading: [series hub](../../series/agentic-software-engineering.md), [blog home](../index.md), or
  [SDD guide](../../sdd.md).
