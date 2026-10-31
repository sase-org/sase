---
title: Agent-initiated launches
description: Look up how an agent starts another session or workflow.
---

# Agent-initiated launches

This page describes session and workflow launches requested by a running agent.

## Agent-Initiated Session Launches

User-initiated launches are direct: prompts submitted through normal launch surfaces,
including prompts containing `%i(suffix, session=parent)`, do not require launch
approval.

When a **running agent** requests another launch, SASE creates a typed `LaunchApproval`
request and spawns nothing until a human approves it. Agents use the generated
`/sase_run` skill and submit a structured request:

```bash
sase launch request -f launch_request.json -o json
```

The request may contain `%i(suffix, session=parent)` in its prompt, so the approved
launch joins an existing session with any valid suffix. `launch_preview.md` shows the
resolved launch plan before approval. Inside an agent, the default immediate path
creates a pending `LAUNCH` gate turn, hands off the session lane, and ends the
requesting turn. With `staged_handoffs` enabled, the request returns `Staged` and the
gate is published after host completion; the root agent must finish through
`/sase_final`. See [Handoff completion](agent-sessions.md#handoff-completion). Its
default `requester_continuation.mode` is `resume_requester`: after approval, rejection,
timeout, or gate/dispatch failure, one successor resumes the original assignment with
the gate decision, feedback, typed launch results, requester identity, workspace/session
context, and the recorded checkpoint. A stopped gate remains terminal. Set the mode
explicitly to `terminal_handoff` when the requester truly has no remaining work; no
settlement branch then resumes it.

The approved helper prompt and requester continuation cannot both target the requester's
session lane. If the stored prompt uses `session=parent` (or names that same session),
target a different session or select `terminal_handoff` so the lane has one owner.
Outside an agent, the request defaults to terminal handoff, prints the creation
descriptor, and returns immediately. A script that needs to block can use its
`request_id` with `sase gate wait -i <request-id> -k launch -j` as a separate step.

Approve or reject from sase's TUI, or use:

```bash
sase launch approve <selector>
sase launch reject <selector> [-f <feedback>]
```

The selector may be a request ID, notification ID, or unique notification prefix.
Approval verifies the neutral request bundle, revalidates and replans the stored prompt
in its original working directory, and records host dispatch status in the write-once
response. A multi-slot launch is all-or-nothing. In-flight requests from the older
launch-request layout remain answerable during the compatibility window.

For the complete request schema, preview behavior, slot limits, and dispatch rules, see
[Launch Approval](../tui/agent-workflows.md#launch-approval) and
`sase launch request --help`.

## Related

- [Agents and workspaces](index.md) — the section hub.

## `sase run`

<a id="cli-options-16"></a> Moved to [sase run](agent-launches.md#sase-run).

<a id="command-behavior-10"></a> Moved to
[Agent-initiated launches](agent-launches.md#command-behavior-10).

## Command behavior {#command-behavior-10}

When invoked with no arguments, opens `$EDITOR` for composing a prompt interactively.
When invoked with `.`, opens a prompt history picker. All prompts launch as detached
background agents, and multi-prompt queries (containing `---` separators) are launched
as sequential detached background agents.

From an interactive terminal outside an agent or durable proc, a prompt whose
[`%hold`](../macros/directive-launch.md#hold-directive) preview combines `future` with
`scope=host` prints the preview and asks `Arm this hold? [y/N]`. An over-threshold
`pending` capture also asks when the preview can resolve project context; typed launch
plans can do so, while a plain project-scoped `sase run` prompt currently cannot and
skips this confirmation. Declining prints `Hold not armed; launch cancelled.` and exits
`1`. Accepting pre-arms the hold before launch admission, then transfers ownership to
the launched runner.

## Daily Operation

Flag and option details live in the generated [CLI command groups](../cli/index.md):

- [sase agent](../cli/agent.md), [sase chat](../cli/chat.md),
  [sase prompt](../cli/prompt.md), [sase stitch](../cli/stitch.md)
- [sase gate](../cli/gate.md), [sase autonomy](../cli/autonomy.md),
  [sase sudo](../cli/sudo.md), [sase notify](../cli/notify.md)
- [sase proc](../cli/proc.md), [sase repro](../cli/repro.md)
- [sase tui](../cli/tui.md), [sase service](../cli/service.md),
  [sase scheduler](../cli/scheduler.md), [sase screenshot](../cli/screenshot.md),
  [sase tmux-agent](../cli/tmux-agent.md), [sase run](../cli/run.md),
  [sase pager](../cli/pager.md)

Workflows: [TUI](../tui/index.md), [Scheduler](../automation/scheduler.md),
[Monitors](../automation/monitors.md), [Prompt history](../prompt-history.md),
[VCS](../vcs/index.md), [Notifications](../automation/notifications.md),
[Macros](../macros/index.md).

`sase stitch list --origin ORIGIN` accepts `stitch`, `auto`, or `manual`; repeat the
flag to OR multiple origins. `sase stitch list --format json` includes the same
canonical value as each commit's `"origin"` field.

`sase run` launches detached background agents that appear in sase's TUI Agents tab. It
can start from prompt text, macro or workflow references, the editor, or the
prompt-history picker, and multi-prompt input expands into sequential background
launches. sase's TUI uses the same launch machinery when users start agents from the
TUI. When `sase run` is used from an interactive terminal (not from inside an agent or a
durable proc) and its [`%hold`](../macros/directive-launch.md#hold-directive) preview is
broad, it prints the preview and asks `Arm this hold? [y/N]`; declining cancels the
launch and exits `1`. A host-scoped hold that includes `future` is always broad. A
`pending` hold is broad when its live capture exceeds
`agent_hold_confirm_capture_threshold`, but that check needs project context: typed
launch plans can resolve it, while a plain project-scoped `sase run` prompt currently
cannot and therefore skips this confirmation. Once accepted, the launch submission
pre-arms the hold before admission can race ahead, then rebinds ownership to the
launched runner. Narrow and non-interactive holds use that same pre-arm path without the
extra prompt.

The short option `-n` is not one flag across commands: `sase agent kill -n NAME` and
`sase agent hold create -n NAME` are `--name` (for `kill` it is required; a bare name is
a usage error), `sase agent drain -n` and `sase agent restart -n` are `--dry-run` (the
agent name or provider is positional), and `sase monitor start -n` is `--next`.
Likewise, `sase agent wait -a` is `--all`: it snapshots the eligible agents running when
the wait starts, while `sase agent list -a` means include recent completed agents in a
list view. `sase agent hold create -p` is `--pending`, not `--project`.

<a id="sase-autonomy"></a> Moved to
[Launch directives](../macros/directive-launch.md#sase-autonomy).

<a id="sase-agent-auto-restart"></a> Moved to
[Agent Auto-Restart](../agent-auto-restart.md#sase-agent-auto-restart).

<a id="sase-agent-search"></a> Moved to
[Query Language Reference](../query-language.md#sase-agent-search).

<a id="sase-agent-wait"></a> Moved to
[Agent sessions](agent-sessions.md#sase-agent-wait).

<a id="sase-agent-hold"></a> Moved to [Agent holds](agent-holds.md#sase-agent-hold).

<a id="sase-service"></a> Moved to
[Service host initialization](service-host.md#sase-service-1).
