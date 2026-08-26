---
title: "[03] AXE — The Background Daemon That Keeps Agent Work Moving"
date: 2026-05-14
draft: true
description: >-
  Agents shouldn't poll. AXE is the background daemon that does the polling for them so
  the engineering workflow keeps moving while individual agents finish, fail, or wait.
categories:
  - Agentic Software Engineering
  - Automation
slug: axe-background-daemon
links:
  - AXE Automation: axe.md
  - Notifications: notifications.md
  - "[02] XPrompts in Depth — From One File to Full Workflows": blog/posts/xprompts-in-depth.md
  - View on GitHub: https://github.com/sase-org/sase
---

# [03] AXE — The Background Daemon That Keeps Agent Work Moving

Agents shouldn't poll. They should write code, hand the result back, and exit. AXE is
the daemon that does the polling for them — so hooks complete, mentors launch,
dependencies unblock, comments get noticed, and error digests get sent while individual
agents finish, fail, or wait.

<!-- more -->

[Getting Started](../../getting_started.md) names AXE as the third tab in the ACE TUI;
this post explains what is actually running behind that tab.

## The Architecture in One Paragraph

AXE is a multi-process daemon. A parent **Orchestrator** spawns and monitors a fixed set
of **Lumberjacks**; each lumberjack is a scheduler loop that runs one or more **Chops**
(jobs) on its own interval. The orchestrator holds a lifecycle lock, forwards `SIGTERM`
to its children on shutdown, and restarts any lumberjack that crashes. The default
lumberjacks and their cadences are: `hooks` (5s), `waits` (10s), `checks` (5m),
`comments` (1m), and `housekeeping` (1h). ACE auto-starts AXE the first time it opens
unless you pass `--no-axe`.

## The Hooks Chop Is Most of the Work

Every five seconds, the `hooks` lumberjack runs a small fleet of high-frequency chops:

- `hook_checks` — complete finished hooks, start stale ones.
- `mentor_checks` — start mentors once hook prerequisites are met.
- `workflow_checks` — complete and start CRS and fix-hook workflows.
- `pending_checks_poll` — poll background check results.
- `comment_zombie_checks` — mark old comment threads as ZOMBIE.
- `suffix_transforms` — strip stale suffixes, update mail-readiness.
- `orphan_cleanup` — release workspace claims for dead processes.
- `stale_running_cleanup` — release dead-process RUNNING claims promptly.

That list is the bulk of "what AXE is doing on your behalf" while you read code. None of
it would be hard to write into a single agent — but you would have to write it into
_every_ agent, and you would have to keep paying for the polling. AXE pays for it once,
in the background, for every agent in the project.

## The Waits Chop Resolves `%wait` Dependencies

[\[02\]](xprompts-in-depth.md) showed how `%wait:agent_name` in a directive declares a
dependency. The `waits` lumberjack is what unblocks it. Every two seconds, `wait_checks`
looks at every parked agent and asks: did the newest matching dependency produce a
`done.json` with outcome `completed`? Only then does it write `ready.json` and let the
agent launch.

The strictness matters. Failed, killed, crashed, still-running, malformed, and missing
`done.json` artifacts do not satisfy the wait. The dependent agent stays parked until a
later successful run of the same dependency name appears. That is what lets you safely
chain `plan → code → review` segments knowing the review will not start if the code
agent crashed — there is no "fail open" on `%wait`.

For multi-agent workflows, every child agent for that root must also be `completed`
before the dependency resolves. So `%wait:my_workflow` does not unblock until the
workflow root _and_ all its children have landed cleanly.

## Comments, Housekeeping, and Everything Else

The `comments` lumberjack (1-minute interval) polls for new review comments and kicks
off critique agents — the back-half of the mentor follow-up loop. The `checks`
lumberjack (5-minute interval) runs `pr_submitted_checks` to notice when a PR has been
submitted upstream, plus a slower backstop pass of `stale_running_cleanup`.

The `housekeeping` lumberjack (1-hour interval) runs four maintenance chops.
`error_digest` summarizes recent errors into
`~/.sase/axe/error_digests/digest_<timestamp>.txt` and posts a notification with a
`ViewErrorReport` action that opens the digest in `$EDITOR` when selected from the ACE
notification modal. The relevant errors are tracked in `~/.sase/axe/recent_errors.json`
(last 100), so the digest is not reconstructed from logs. `managed_tmp_reap` bounds
SASE-managed scratch, `bead_stale_cleanup` batches stale sub-threshold ready tasks into
a human cleanup gate, and `artifact_link_backfill` derives and reconciles typed links,
drains audited reads after agent publication, and repairs refs after Git renames. Each
is bounded so a neglected backlog converges across ticks without turning the hourly lane
into an unbounded scan.

## The Lumberjack Control Surface

Day-to-day AXE is invisible. When something looks wrong, the inspection surface is small
and shell-friendly:

```bash
sase axe lumberjack status          # all lumberjacks: uptime, error counts, last tick
sase axe lumberjack list            # configured lumberjacks and their chops
sase axe lumberjack run hooks       # run one lumberjack in the foreground for debugging
sase axe chop run hook_checks       # run one chop once, in the foreground
```

The orchestrator itself is `sase axe start` / `sase axe stop`. Start is idempotent — if
an orchestrator PID is already live, it returns that PID without spawning a second one.

## Maintenance Mode Pauses Scheduled Work Safely

`sase axe maintenance enter --reason "install plugin update"` writes
`~/.sase/axe/maintenance.json` with the reason, caller PID, and start timestamp. Each
lumberjack reads that marker at the top of every tick and skips its chops while it
exists. `sase axe maintenance exit` clears the marker; `sase axe maintenance status`
exits 0 when active and 1 when inactive, so scripts can use it as a guard.

The reason maintenance mode exists at all: AXE polling against a workspace that is being
moved, a plugin that is being reinstalled, or a config that is mid-edit produces
spurious failures. Pausing for the duration of the operation is cleaner than chasing the
resulting noise. Stale markers (older than 24 hours, malformed, or owned by a dead PID)
are cleared automatically on the next tick.

## Don't Run Heavy Work Inside a Chop Tick

A chop is a short job, not a long-running computation. The hooks lumberjack ticks every
five seconds; a chop that takes thirty seconds to run will block the rest of the tick
and back the lumberjack up. If a piece of work needs to take real time, it should be an
agent (launched from a chop, returning a `done.json`) rather than a body of work
performed inline in the chop. AXE's `SharedRunnerPool` enforces global limits on hook
runners and agent runners separately, with cross-process coordination via `fcntl.flock`
on `~/.sase/axe/shared/runner_count` — so the design already assumes chops launch and
supervise, not compute.

## What To Read Next

- [AXE reference](../../axe.md) — chop definitions, lumberjack configuration, state
  directory layout, agent completion artifacts, ACE integration.
- [Notifications](../../notifications.md) — how AXE's error digests, plan approvals, and
  workflow completions surface to the operator.
- [\[04\] Beads and SDD — Planning Multi-Agent Work That Actually Lands](beads-and-sdd.md)
  — what AXE is unblocking when multi-phase epic work executes.
