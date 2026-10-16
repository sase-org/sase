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
resolved launch plan before approval. Inside an agent, the request creates a pending
`LAUNCH` gate turn, hands off the session lane, and ends the requesting turn. Its
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
