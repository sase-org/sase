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
as first-class artifacts on disk. The two files cross-reference each other via `prompt:` and `plan:` frontmatter fields,
and `sase sdd validate` checks that the link graph is intact.

Two plan tiers share one canonical plans root:

- **Tales** — ordinary implementation plans at `<plans-root>/{YYYYMM}/{name}.md` with `tier: tale`.
- **Epics** — executable multi-phase plans at the same path shape with `tier: epic`.

Storage follows workspace-provider policy. Built-in bare-git projects use in-tree `sdd/`; newly initialized managed
GitHub projects use split `--plans` and `--research` companions; unmigrated GitHub projects retain their `.sase/sdd/`
clone; providerless projects use the primary workspace's local `.sase/sdd/` store. A positive companion-store record
preserves the resolved GitHub layout for offline use.

`sase sdd list -k epics` lists every epic; `sase sdd validate` checks the prompt/plan link graph; `sase sdd init`
materializes provider-owned storage and refreshes the generated READMEs and directory-map asset. The reference is in
[`sdd.md`](../../sdd.md).

## Beads Are the Work Unit

A **bead** is a git-portable issue record backed by a canonical append-only event store. Status moves through `open` →
`in_progress` → `closed`. Beads have dependency edges. Each one can carry a plan reference (the `design` field), a tier
(`plan` or `epic`), and a model annotation (`-m/--model`). Storage lives under the resolved SDD store: `events/**` is
the source of truth, `issues.jsonl` is a generated compatibility projection, and `beads.db` is a gitignored
compatibility cache. Fresh clones read the tracked event store directly and can rebuild the mirrors on demand.

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

Because every segment uses `%id:!<agent_name>` (force-reuse) and bare `%auto`, `sase bead work` is safe to retry after a
killed or failed run while still auto-approving submitted phase and landing plans. Those agents may author a tale or an
epic as needed; the plan's authored `tier` selects the automatic follow-up path. AXE's `wait_checks` chop is what
unblocks each phase the moment its blockers have `done.json` outcomes of `completed`. Failed or killed phases keep the
land agent parked until that phase name retries successfully — there is no fail-open.

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
clone; with split storage, it instead uses `beads/` in its auto-cloned `--plans` repository.

That keeps the source of truth inspectable and unsurprising. For in-tree work, bead state moves between checkouts
through the same VCS sync path as code and SDD files, and ID allocation uses the active checkout's local `config.json`
and canonical event state. Providerless local stores are shared through the primary workspace; provider companions
synchronize through the clone in the active workspace.

## What To Read Next

- [Spec-Driven Development](../../sdd.md) — full reference for tales, epics, research, storage modes, bead integration.
- [Beads](../../beads.md) — every `sase bead` subcommand, the data model, and the current-checkout source-of-truth rule.
- [\[05\] Commit Workflows — The Pluggable Path From Diff to PR](commit-workflows-plugins.md) — how the work that
  `sase bead work` schedules eventually lands as commits, proposals, or PRs.
