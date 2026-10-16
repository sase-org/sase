---
title: Notification CLI
description: Command-line operations for listing and managing notifications.
---

# Notification CLI

This page names notification and gate CLI behavior that is not only a flag table. See
the generated [`sase notify`](../cli/notify.md) page for flags and subcommands.

## CLI

The `sase notify` command can create notifications and inspect the local notification
inbox.

Bare `sase notify` is a read-only shortcut for `sase notify list`. Use
`sase notify create` when writing a notification from JSON input:

```bash
echo '{"sender": "test", "icon": "👋", "notes": ["Hello"], "tags": ["review"]}' | sase notify create
echo '{"sender": "audit", "notes": ["Background result"], "silent": true}' | sase notify create
sase notify create -s my_sender < notification.json
sase notify create -s my_sender --tag review --tag handoff < notification.json
sase notify +1 6f8a2 "same failure reproduced on macOS" -s ci_watch
sase notify +1 -k ci/sase-main "failure reproduced again" -s ci_watch
```

`sase notify rules` shows the configured
[delivery rules](notifications.md#delivery-rules) in the order they are consulted, and
`sase notify rules -e ID` explains which rule decides the toast and the sound for one
stored notification. It never changes notification state.

Raw creation validates and preserves the optional single-glyph JSON `icon`, the optional
`#RRGGBB` JSON `color` (see [Tab colors](notification-tags.md#tab-colors)), and the JSON
`silent` field. It rejects registered privileged actions (`PlanApproval`,
`EpicApproval`, `TaskTriage`, `BeadSnooze`, `FlagTriage`, `BeadStaleCleanup`,
`PluginsRequired`, `UserQuestion`, `LaunchApproval`, `SudoRequest`, `CustomGate`, and
`HITL`) because a raw row has no trusted command bundle.

`sase notify +1 [ID] NOTE` accepts an exact notification ID or unique prefix. With
`-k/--dedup-key`, it instead selects the newest row matching the resolved sender and
key; pass `-s/--sender` explicitly when producer identity matters. Otherwise the sender
is the current SASE agent identity, falling back to the OS user. An ID miss exits
non-zero; a dedup-key miss emits `{"action":"no_match"}` and exits zero so producers can
decide to create a fresh row.

Producers can make that decision atomically with `sase notify create -k KEY -p NOTE`.
When no `(sender, key)` row exists, SASE creates the input notification with that key;
when one exists, it appends `NOTE` and does not create a duplicate.
`-S/--supersedes OLD_KEY` applies only on the create branch: it retires matching old-key
rows by appending a superseding `+1` and dismissing them. It is ignored when the current
key already matches a row. The same three values can be supplied as JSON `dedup_key`,
`plus_one_note`, and `supersedes` fields.

The first-class gate API reads a versioned gate specification from stdin:

```bash
sase gate create < gate-request.json
```

For example, this custom gate offers a restart-and-verify group plus a separate
rejection branch:

```json
{
  "schema_version": 3,
  "kind": "custom",
  "request_id": "restart-api",
  "producer": { "agent": "maintenance" },
  "continuation_mode": "resume_agent",
  "gate_timeout_seconds": 900,
  "presentation": {
    "sender": "maintenance",
    "icon": "🛡️",
    "notes": ["Restart the API after reviewing the health report?"],
    "panel": "deployments",
    "panel_icon": "🚀",
    "origin_agent": "maintenance.agent",
    "chip": { "glyph": "🚀", "label": "deploy", "color": "#5FD75F" },
    "preview": "preview.md"
  },
  "query": "(restart AND verify) OR reject",
  "primary_branch": ["restart", "verify"],
  "options": [
    {
      "id": "restart",
      "label": "Restart service",
      "icon": "🚀",
      "default_selected": true,
      "feedback": "required",
      "command": { "argv": ["commands/restart"] }
    },
    {
      "id": "verify",
      "label": "Verify service health",
      "icon": "🩺",
      "default_selected": true,
      "feedback": "disabled",
      "command": { "argv": ["commands/verify"] }
    },
    {
      "id": "reject",
      "label": "Do not restart",
      "icon": "❌",
      "feedback": "optional",
      "command": { "argv": ["commands/reject"] }
    }
  ],
  "groups": [
    {
      "options": ["restart", "verify"],
      "label": "Restart service",
      "icon": "🚀"
    }
  ],
  "resources": [
    {
      "path": "commands/restart",
      "role": "command",
      "content": "#!/bin/sh\nprintf '{\"status\":\"restarted\"}\\n'\n"
    },
    {
      "path": "commands/verify",
      "role": "command",
      "content": "#!/bin/sh\nprintf '{\"status\":\"healthy\"}\\n'\n"
    },
    {
      "path": "commands/reject",
      "role": "command",
      "content": "#!/bin/sh\nprintf '{\"status\":\"rejected\"}\\n'\n"
    },
    {
      "path": "preview.md",
      "role": "preview",
      "content": "# API health report\n\nAll checks passed.\n"
    }
  ],
  "auto": false
}
```

`presentation.panel` selects the named notification panel tab described in
[Tags](notification-tags.md#tags), and **requires** `presentation.panel_icon` alongside
it — a gate that names a tab is the thing introducing that tab to the user, so it is the
thing responsible for saying what the tab looks like. Omitting `panel_icon` while
declaring `panel` fails gate creation with a `missing_presentation` error.
`presentation.origin_agent` attributes the gate to the agent it was filed on behalf of;
it is stripped, limited to 128 characters, and stored without consulting the local agent
registry so remote agent names remain valid. All three fields are projected into
notification `action_data` as `panel`, `panel_icon`, and `origin_agent`; producers may
not write those protected keys directly through `presentation.action_data`.

`presentation.chip` is an optional subject chip: an object with `glyph` (required, one
grapheme), `label` (required, stripped, non-empty, single-line, free of control
characters, and at most 32 characters), and `color` (optional `#RRGGBB`). A declared
chip is projected into notification `action_data` as `gate_chip_glyph`,
`gate_chip_label`, and `gate_chip_color`; a colourless chip writes only the first two
keys. Those keys are protected: producers may not write them through
`presentation.action_data`. Every render surface — sase's TUI toast, the notification
row, the gate detail pane, the review modal, and the mobile bridge row — reads the
stored keys only and never resolves a task type. A stored colour that is not `#RRGGBB`
is ignored so the glyph and label still render; a missing glyph or label drops the chip.

Every gate whose subject is a typed task bead declares this chip from the presentation
frozen at gate creation (the type glyph, the slug as the label, and the type accent) and
adds the compact typed facts line as `notes[1]`. An untyped bead declares no chip.

`presentation.title` is the one-line decision headline shown in the notification panel's
[gate detail pane](notifications.md#gate-detail-pane) and in the custom gate review
modal's header. It is stripped, limited to 120 characters, must be a single line, and
must not contain control characters; a missing title falls back to the gate kind's
display title (for example `Custom Gate`). It is **required for `kind: "custom"`** —
along with a non-empty `presentation.icon` and at least one non-blank
`presentation.notes` entry — because a custom gate has no other source for the headline,
icon, and context the panel renders. `plan`, `epic_plan`, `question`, `launch`, and
`hitl` gates keep their existing contracts and do not require a title.
`presentation.title` is projected into notification `action_data` as `gate_title`;
producers may not write that protected key directly through `presentation.action_data`.

`presentation.color` suggests the `#RRGGBB` accent for the tab the gate's notification
lands in, as described in [Tab colors](notification-tags.md#tab-colors); a malformed
value fails gate creation with an `invalid_color` error.

`presentation.panel_icon` suggests one emoji or display glyph for the tab the gate's
notification lands in, as described in [Tab icons](notification-tags.md#tab-icons); a
malformed value fails gate creation with an `invalid_presentation` error. It is a
separate field from `presentation.icon` rather than a reuse of it, because
`presentation.icon` is the **row's** icon and rows sharing one panel legitimately differ
— donating the row icon to the tab would make the tab's glyph flip depending on which
row arrived most recently. `panel_icon` is a property of the tab, and gates sharing a
panel are expected to agree on it.

`presentation.icon`, `option.icon`, and `group.icon` each accept one emoji or display
glyph. Each `OR` branch is a mutually exclusive resolution path. A singleton branch
renders as one button; an `AND` branch renders selectable option toggles plus a submit
button. The selected ids must be a non-empty subset of exactly one branch.
`default_selected` defaults to true, and a matching `groups` entry configures an AND
branch's submit label and icon. `feedback` is `disabled`, `optional`, or `required`;
custom options default to `optional`, and a group selection uses the strongest mode
among its selected members. Automatic resolution runs the creator's autonomy record
through one core evaluator over explicit policy option IDs — never `primary_branch`,
`default_selected`, or option order — so reordering the branch or switching the defaults
off leaves the automatic outcome unchanged. Only the plan, epic-plan, and question kinds
can auto-resolve; every other kind, including custom gates, always waits for a human.
Each evaluation writes a `policy` block (`profile`, `selection`, `rule`, `outcome`,
`value`, `option_ids`, `source`, `revision`, `digest`) into the request envelope's
`auto` block and the creation result's `auto_resolution`, and, for automatic outcomes,
into the gate response as well. `primary_branch` must name one complete branch in
canonical query order. sase's TUI submits it with Enter while Space toggles the focused
AND member; submitting a primary group preserves the reviewer's current toggles. sase's
TUI also numbers top-level branches in canonical order: the fixed keys `1`–`9` submit
their matching branches directly. AND-member toggles remain unnumbered.

Every option references a bundle-owned `command` resource and is executed in query order
as an argv array without a shell after its hash is reverified. A selected-command
failure is recorded in the bundle error log and leaves the gate answerable. The
write-once response records `selected_option_ids`, `option_results`, and normalized
top-level `feedback` consistently for every transport.

On success, creation prints a stable JSON descriptor containing `schema_version`,
`notification_id`, `request_id`, `kind`, bundle/request/response/preview paths,
`continuation_mode`, `auto_resolution`, and hashes. The descriptor's `request_id` and
`kind` are the exact values accepted by `sase gate wait`. Typed front doors such as
`sase plan propose`, `sase questions`, and agent-initiated launch requests call the same
in-process gate service directly; they do not spawn this CLI. Agents should normally use
the generated `/sase_gate` skill to author this JSON.

Wait mechanically for a gate without reading or polling bundle files directly:

```bash
sase gate wait --id <request_id> --kind <kind>
sase gate wait --id <request_id> --kind <kind> --json
sase gate wait --id <request_id> --kind <kind> --timeout 60
```

Human output is colored and summarizes the selected options, feedback, response path,
and any failed execution recovery commands. `-j/--json` emits the stable shape `status`,
`selected_option_ids`, `feedback`, and `response_path`, plus `input`, `option_inputs`,
and `option_results` off the write-once response (populated only once the gate is
answered), `operations` from the execution journal, and for failed execution `failure`
plus `failure_recovery` (`error_report_path` and exact resume, restart, or cancel
commands when they are safe to run). Status is `answered`, `cancelled`, `timeout`, or
`failed`, with exit codes 0, 3, 4, and 5 respectively. A CLI timeout can shorten but
never extend the request's own gate timeout.

`sase gate answer`, `sase gate act`, and `sase gate show` are the headless counterparts
to sase's TUI modals: `answer` selects a branch and supplies each selected option's
declared input (`--set field=value` typed by its declaration,
`--option-input <opt>=@file.json` for a whole per-option value, or `--input @file.json`
for the shared value) and resumes or restarts a partially executed AND branch with
`--resume` / `--restart`. On an already-answered turn-backed tale whose selected branch
requested a coder, `--resume` retries only that unfinished handoff: it reuses the stored
answer, skips option commands and plan archival, and launches nothing when the successor
is already recorded. Conflicting `--option` / input values are refused. `--restart`
still means "run the whole option branch again" and does not recover a coder handoff.
`act` runs one declared action headlessly, including opening `$EDITOR` for an
`edit_file` action, without answering the gate; `show` prints a gate's declared
branches, each option's input fields, and its declared actions, so an author can check
that the gate they wrote asks for what they intended. When a decision has been accepted
but its execution has not written `response.json` yet, `show` adds an **Acceptance**
block (an `acceptance` object with `--json`) with the accepted options, the submitting
surface, and the latest recorded execution error, or flags an invalid decision receipt.
See `--help` on each for the full flag reference.

For read-only inspection, list recent notifications as either a compact table or stable
JSON:

```bash
sase notify
sase notify list
sase notify list -j -l 20
sase notify list -j --sender axe
sase notify list -j --unread
sase notify list -j --tag done
sase notify list -j --tag memory
sase notify list -j -q digest
sase notify list -j --all
```

Use the explicit `list` subcommand when passing list flags; for example, use
`sase notify list -j`, not `sase notify -j`.

`sase notify list -j` prints notifications newest first with `id`, `timestamp`, `age`,
`sender`, `icon`, `priority`, `notes`, `files`, `tags`, `action`, `action_data`, `read`,
`dismissed`, `silent`, `muted`, `snooze_until`, and `resurfaced_at`. The `-q/--query`
filter matches tags as well as ids, senders, notes, files, actions, and action data.
Dismissed notifications are hidden unless `--all` is provided.

`list` and `show` are current-state reads: they atomically expire any due snooze before
projecting, and they order and limit by the activity key, so a resurfaced old
notification appears on the first `-l 1` page while still reporting its original
`timestamp` and `age`.

Inspect one notification by id:

```bash
sase notify show --id <notification_id>
sase notify show --id <notification_id> -f json
sase notify show --id <notification_id> -f markdown
```

The default `show` format is markdown. It includes the notification tags, notes,
attached file paths, action data, and state flags. Axe error digest notifications
usually point to the actionable report through `files` or
`action_data.error_report_path`; read that attached file for the detailed errors. Gate
execution failures use action `GateExecutionFailed`, deterministic ids scoped to the
gate and accepted receipt, tags `gate`, `execution`, and `error`, and action data with
`error_report_path` plus the exact safe resume, restart, and cancel commands.

To create a local test notification with a persistent PNG attachment for sase's TUI
modal image-preview checks, run `tools/test_image_notification` from the repository
root.

See [`sase notify`](../cli/notify.md#sase-notify) for the full CLI reference.

## Related

- [Notifications](notifications.md)
- [Notification types](notification-types.md)
- [`sase notify`](../cli/notify.md)
- [Automation migration notes](../upgrading/automation.md)

## `sase notify`

With no subcommand, `sase notify` defaults to the compact `sase notify list` view. Use
`sase notify list` for JSON, limit, query, unread, dismissed, or the clearest sender/tag
filtering form. Use `sase notify create` to write a raw, non-privileged notification
from stdin JSON. Use `sase gate create` and `sase gate wait` for command-backed gates.

<a id="cli-options-45"></a> Moved to [sase notify](notification-cli.md#sase-notify).

<a id="command-behavior-29"></a> Moved to
[Notification CLI](notification-cli.md#command-behavior-29).

## Command behavior {#command-behavior-29}

Raw creation accepts JSON `icon`, `tags`, and `silent` fields plus repeatable
`-t/--tag`; icons must be one emoji or display glyph, and CLI tags are appended to JSON
tags, then normalized and deduplicated. Raw creation cannot create a registered
privileged gate action. The query form, `sase notify list -q`, also matches tags, and
`sase notify list --tag <tag>` filters to notifications with that exact normalized tag.

`notify +1` never changes read, dismissed, muted, snoozed, ordering, or delivery state.
When `notify create` uses a dedup key, `--plus-one-note` is required: it is appended on
a match, while a miss creates the row. `--supersedes` identifies an old sender-scoped
key to annotate and dismiss only when that miss creates the replacement; it has no
effect when the current dedup key already matches a row. See
[Notification `+1` Evidence](notifications.md#1-evidence).
