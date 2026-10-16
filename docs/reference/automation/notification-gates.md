---
title: Command-backed interaction gates
description:
  Gate decisions, inputs, actions, and continuation behavior for SASE interactions.
---

# Command-backed interaction gates

This page describes command-backed interaction gate behavior and lifecycle.

<a id="command-backed-interaction-gates-1"></a>

## Command-backed interaction gates

Each new gate is written once under `~/.sase/interaction_requests/<kind>/<request-id>/`.
The bundle contains canonical `request.json`, eventual write-once `response.json`,
reviewed previews or attachments, and adapter-owned commands. The request records the
continuation mode, optional gate timeout, typed payload, presentation metadata and icon,
option-query branches, the declared primary branch, options with configurable icons and
feedback modes, AND-group submit metadata, input/result schemas, and hashes for the
request and owned resources. Commands are argv arrays executed without a shell. A gate
may also declare repeatable, non-terminal **actions** the reviewer can run any number of
times without answering the gate; see [Gate actions](#gate-actions) below.

Manual creation succeeds only after the bundle, notification row, and pending-action
registration are durable. A partial failure is compensated, and retries are idempotent
by request ID. Manual and automatic selections use the same hash, input, result, and
write-once response validation. The pending-action 24-hour stale threshold is
transport-only; it may hide remote controls but does not terminate a waiting producer.
Only cancellation or an explicit per-request gate timeout is terminal. Every terminal
response or cancellation marks the pending action handled and dismisses the notification
row, regardless of gate kind or client surface. When sase's TUI opens the notification
modal, it also repairs live gate rows whose bundles became terminal without a
corresponding dismissal.

sase's TUI, Telegram, and mobile derive gate-kind capabilities from the shared adapter
registry and render branches in query order from the same normalized envelope structure.
Registering a new branch-actionable kind therefore makes it actionable on every surface
without adding per-surface action or kind allowlists. Singleton branches are buttons.
AND branches expose one toggle per option and a configurable submit control; the primary
AND branch starts expanded. Top-level branches have fixed one-based digit selectors in
canonical query order, while AND members remain unnumbered and use Space to toggle.
sase's TUI Decision column shows those branches and toggles only — typed fields live in
a dedicated input panel, not in the left pane. Enter submits the declared primary
branch, Ctrl+S submits the active branch, and `q` or Escape cancels the modal. A
selection that needs typed input — any declared `inputs` field, a raw `input_schema`
with a property the host does not already collect, or `feedback: required` — opens the
panel first; confirming the panel submits the branch, and cancelling returns to the gate
with the selection and whatever was typed intact. An option that declares only
`feedback: optional`, or nothing at all, still answers on Enter or its digit. Press `i`
on the focused option first to open the same panel for an optional note. For an AND
group, the panel opens when the group's submit control is activated, not when a member
is toggled, and then shows one section per selected option that declares input. Surfaces
submit `selected_option_ids`, feedback, and each selected option's declared input (see
[Gate inputs](#gate-inputs) below), and the shared executor runs the selected commands
in query order.

| Key             | Action                                                                                         |
| --------------- | ---------------------------------------------------------------------------------------------- |
| `j` / `k`       | Focus the next / previous branch control                                                       |
| Space           | Toggle the focused AND member                                                                  |
| Enter           | Submit the declared primary branch; opens the input panel first when the selection needs input |
| Ctrl+S          | Submit the active branch; same panel rule as Enter. Inside the panel, submit from anywhere     |
| `i`             | Open the input panel for the focused option's note or declared fields                          |
| `1`–`9`         | Submit the matching top-level branch                                                           |
| Tab / Shift+Tab | In the input panel, walk the next / previous field (wraps; includes the buttons)               |
| `q` / Escape    | Cancel the review modal. In the panel, Escape leaves INSERT, then closes without submitting    |

Tale plan approval uses `(approve AND commit) OR reject OR feedback`. The approve and
commit options start selected, the group submit is labeled **Tale**, and the two
singleton branches remain **Reject** and **Send Feedback**. Epic plans use
`approve OR reject OR feedback`.

### Plan Decisions

A tale or epic plan may declare typed Plan Decisions in `decisions:` frontmatter. Start
with the [authoring example and CLI review flow](../../sdd.md#plan-decisions) for
user-facing usage; this section describes the gate protocol. `decision_<id>` fields are
treated as already collected, so they do not appear as extra inputs. Override a default
with `sase gate answer` and `--set decision_<id>=...`.

Gate build freezes them into `payload.decisions` and compiles `decision_<id>` raw
properties onto tale `approve`, `commit`, and `feedback` (epic `approve` and
`feedback`). Toggles compile to `{"type": "boolean"}`; choices compile to
`{"enum": [keys]}` in author order. They are never required, and `additionalProperties`
stays `false`. Approve and commit result schemas gain a required `decisions` object with
the same fully-resolved value types.

Normalization runs once at the top of `execute_gate_selection`, before
`accept_gate_decision`, and its output feeds both the receipt and execution paths.
Omitted ids take their effective default, so an omitted value and an explicit default
share one `input_identity`. Disagreeing `decision_*` values across selected options fail
as `decision_conflict` before any receipt or command. An agent memory value of true
fails as `memory_decision_requires_human` unless its effective default is already true
(a verified `asked`, `correction`, or `inherited` row). `claim_not_found` rows stay off
under no-human review and join the unrequested set for coder follow-up.

Submissions carry the displayed `review_revision`. A mismatch fails as `stale_review`
before any side effect; an absent revision stays unchecked so mobile and older clients
keep working. In-gate edits may change prose but never anything under `decisions:`; the
freeze compares the digest of a rebuild against `payload.decisions` and refuses with the
Decisions-panel message.

Approval writes the resolved answers and reviewer provenance into the durable plan.
Feedback carries changed values to the next planner as provisional choices, including an
explicit reminder that provisional memory choices are not authorization.

The typed projections remain deliberately distinct. Their default feedback, generic-form
rendering, and branch-action capabilities are declared by the same adapter entries that
map kinds to notification actions:

| Gate kind            | Notification action | Recommended producer                              |
| -------------------- | ------------------- | ------------------------------------------------- |
| `plan`               | `PlanApproval`      | `sase plan propose` with an authored `tier: tale` |
| `epic_plan`          | `EpicApproval`      | `sase plan propose` with an authored `tier: epic` |
| `task_triage`        | `TaskTriage`        | AXE's built-in `bead_task_triage` job             |
| `bead_snooze`        | `BeadSnooze`        | AXE's built-in `bead_task_triage` job             |
| `flag_triage`        | `FlagTriage`        | AXE's built-in `bead_task_triage` job             |
| `bead_stale_cleanup` | `BeadStaleCleanup`  | AXE's built-in `bead_stale_cleanup` job           |
| `plugins_required`   | `PluginsRequired`   | AXE's built-in `plugins_required` job             |
| `question`           | `UserQuestion`      | `sase questions`                                  |
| `launch`             | `LaunchApproval`    | Agent-initiated `sase launch request`             |
| `hitl`               | `HITL`              | A workflow `HITL` step                            |
| `sudo`               | `SudoRequest`       | Agent-initiated `sase sudo request` (beta)        |
| `custom`             | `CustomGate`        | `sase gate create`                                |

`SudoRequest` gates use `approve OR deny`. Approval requires a terminal and is accepted
only from `sase sudo answer`, while denial works from any surface; see
[Sudo Requests](sudo.md).

`TaskTriage` uses `launch OR close OR snooze`, with Launch as the primary branch. Launch
accepts optional feedback and submits or reuses one globally visible unattributed proc
whose command is `sase bead work <bead-id> --yes-to-all`; the gate response records that
proc ID. Close requires feedback, closes the task bead with `resolution=canceled`, and
uses the feedback as its close reason. Snooze requires a wake-time expression and moves
the task to `snoozed`, after which reconciliation replaces this gate with a `BeadSnooze`
gate. The gate preview is generated from the bead's title, description, and notes, with
the notes section present only when the bead has notes. Automatic resolution is
forbidden, and all client surfaces use the same host-side side effects.

Inside a running SASE agent, workflow `HITL` now uses the same gate-turn handoff as
questions and plans. Historical HITL bundles remain readable and use their compatibility
response-file path; every neutral bundle is resolved through the same hash-verified
executor in sase's TUI and Telegram.

### Fast decision acceptance

Gate answers are split into fast decision acceptance and slower command execution.
Before a selected option runs its commands, the shared executor writes a durable,
write-once `decision_receipt.json` under an acceptance lock. The receipt binds the
request hash, selected option IDs, typed input identities, feedback identity, submitting
surface, acceptance time, and execution owner. An identical duplicate selection replays
the accepted decision; a conflicting selection fails before any command runs.
Cancellation is refused while the execution owner is alive. A conflicting answer while
the owner is live fails promptly with `gate_decision_conflict`; it never replaces the
receipt of a running attempt.

`decision_receipt.json` is the local signal for immediate notification dismissal and
targeted sase's TUI refresh. `response.json` remains the terminal execution record
written only after the command set and archive work have completed.

#### Approved versus committed status

The decision status and the execution status are separate:

- `TALE APPROVED` and `EPIC APPROVED` (and the reject and feedback labels) derive from
  the acceptance receipt on every load path. They mean the human decision is durable,
  not that anything has finished, and they never free a worker's resources.
- `PLAN COMMITTED` and other execution-dependent labels appear only after the archive
  succeeds. If the archive fails, the label is rolled back.
- A durably recorded failure outcome shows as a distinct failed status that the approved
  label cannot hide.
- `response.json`, the turn's terminal state, and the refresh pulse are published before
  post-terminal epic launch preparation, so sase's TUI does not wait on the follow-up
  launch.

#### Failure outcomes and recovery

Every failure after acceptance (an option command, terminal preparation or archive, a
side effect after `response.json`, or a `GateError` raised after acceptance) writes one
redacted `attempt_failed` journal event. It carries the attempt id, the failed stage
(`command`, `terminal_prepare`, `side_effects`, or `follow_up`), an error code and
message, and a timestamp, never raw input values, and it references the existing
`errors/*.json` record. `attempt_completed` is journaled only after terminal preparation
succeeds.

A failure publishes one deduped `GateExecutionFailed` notification per gate and attempt.
Failures in the `command` and `terminal_prepare` stages offer resume, restart, and
cancel; later stages offer resume only. A later successful attempt dismisses it.
`poll_gate` and waiting requesters receive the failure result instead of a pending or
`already_answered` state. The recovery actions work in sase's TUI even after the
original review notification was dismissed, and `partial_attempt` plan gates reuse the
gate retry modal.

- `resume` skips completed option commands and retries only archive and terminal
  preparation.
- `restart` re-runs the selected commands.
- `cancel` settles the gate without a follow-up.

In sase's TUI, pressing `Enter` on a `GateExecutionFailed` row in the notification panel
opens a `Gate execution failed: <stage>` dialog listing the completed and failed
options:

| Key         | Action                                                                    |
| ----------- | ------------------------------------------------------------------------- |
| `r`         | Resume after the failed step                                              |
| `R`         | Run the whole branch again (`command` and `terminal_prepare` stages only) |
| `c`         | Cancel the gate (`command` and `terminal_prepare` stages only)            |
| `e`         | Open the error report in `$EDITOR`                                        |
| `Esc` / `q` | Close without acting                                                      |

`r` and `R` need the selected option IDs from the failure bundle; when those cannot be
recovered, `R` is hidden. When no recovery action applies (no bundle, or a post-response
stage without recoverable options), `Enter` opens the error report directly.

A recorded failed outcome, or an execution owner that is provably dead, makes the
receipt supersedable, so a different answer or a cancel is accepted.

#### Old in-flight bundles

Bundles accepted before receipts existed have no `decision_receipt.json`. They keep
working: labels come from `agent_meta.json` and `response.json` as before, and they
finish through the historical `response.json` path.

An accepted decision whose execution has not finished is protected from cleanup.
`sase gate cancel` leaves that turn as it is, the `gate_turn_reclaim` housekeeping job
never settles it as lost or timed out, and `sase gate show` reports it in an
**Acceptance** block. A receipt whose attempt failed partway, or whose owner died, is
superseded by the next submission instead of blocking it. sase's TUI submits gate
decisions, including plan and epic approvals, as a tracked `sase gate answer` proc, so
an accepted decision keeps running after the modal closes.

Rollout keeps existing bundles readable. Upgrade `sase-core` first so every surface has
the indexed turn lookup and acceptance policy. Then upgrade the SASE Python package,
sase's TUI, and mobile clients against that binding, and finally upgrade Telegram so its
receiver submits answers through the same supervised proc path. In-flight legacy gates
still fall back to their historical `response.json` path. Telegram receiver adoption
requires no config edit beyond enablement: the plugin declares a `telegram_receiver`
service proc that ships disabled, so enable it in the owning machine's overlay and the
sase service keeps it running. `--once` remains the diagnostic direct poll path, and
disabled or credential-less receivers self-terminate. Control it with
`sase service proc stop|restart|disable telegram_receiver`. A TUI update restarts the
service host and therefore the receiver; a CLI `sase update` restarts only the
scheduler, so restart the receiver manually after a package upgrade to load the current
code.

Latency evidence from isolated probes on 2026-09-14:

- Exact turn lookup over 5,002 fixture artifacts had p50 1.317 ms, p95 3.755 ms, and max
  13.008 ms across 25 lookups. Index rebuild took 3.554 s off the click path. The target
  resolved to the owning gate turn rather than a later inherited-code successor.
- Ten blocked-command acceptance runs wrote `decision_receipt.json` at p50 18.95 ms, p95
  21.6 ms, and max 22.53 ms. Notification dismissal followed at p50 35.37 ms, p95 44.47
  ms, and max 46.35 ms, while `response.json` stayed unwritten until the held command
  was released.

Matched before/after evidence for the two refresh paths, from isolated fixtures on
2026-09-20:

- Acceptance receipt to Agents row data, over a 1,500-artifact synthetic archive: the
  acceptance pulse now lands inside the answered agent's own directory, so it names an
  exact row instead of falling through to a project-level pulse. The broad tier-1 load
  that route used to force cost p50 74.8 ms, p95 123.4 ms, and max 185.6 ms; the exact
  artifact-dir delta that replaces it costs p50 1.7 ms, p95 2.5 ms, and max 2.5 ms
  across 25 runs — about 44x cheaper at the median.
- Response publication to refresh-pulse visibility, across ten settlements holding a 150
  ms follow-up-launch barrier: the pulse now fires at p50 97.7 ms, p95 130.3 ms, where
  the old ordering would not have published it until p50 407.5 ms, p95 450.8 ms —
  roughly 310 ms earlier at the median, and unbounded by however long the follow-up
  launch actually takes.

These measurements exercise local durability and notification behavior only. Live
Telegram callback acknowledgement, message delivery, and keyboard edits remain bounded
by Bot API round-trip time and rate limits; terminal keyboard cleanup is retried from
the on-disk tombstone when a remote edit fails.

### Gate turns and continuation

A gate turn is a named, non-LLM member of an agent session, normally `--gate` or
`--gate-N`. It makes a user decision durable without keeping the asking provider process
or a runner slot alive. The turn can retain the session's workspace claim while pending,
records approved command output in `gate.log`, and settles only after the selected
commands finish. Its lifecycle is pending, settling, answered, completed, failed,
timeout, stopped, or lost. Answered commands start right away even when every runner
slot is busy. A free slot is claimed so a follow-up agent can inherit it, but a full
queue never delays the decision itself.

The hourly `gate_turn_reclaim` housekeeping job settles pending turns whose gates were
already answered, cancelled, or removed. It also times out gates past their own
`gate_timeout_seconds` deadline, and it marks a turn lost once
[`gate.turn.reclaim_grace_seconds`](../config/agents-and-runners.md#gate) (one hour by
default) has passed after that deadline. Reclaim skips a turn whose gate creation is
still running (its session's gate-creation lock is held), so an `%auto` gate that is
still executing its selected commands is never marked lost; a turn whose creator died
before recording a bundle is still settled lost on a later pass.

Agent-side gate creation also writes a per-process intent marker before slow setup work
starts. A clean creation error or the normal runner handoff clears it. If the provider
turn ends while a marker remains, the host waits up to 60 seconds for a creator that is
still running to hand off. Otherwise it writes `gate_intent_lost.json` evidence to the
agent's artifacts and fails the run with a `gate intent lost:` error. The error names
the gate kind and request ID and points at `sase gate list --all`
(`sase sudo list --all` for a sudo gate). That failed run is never retried.

The built-in front doors choose statuses and continuation policy for their domain:

- `/sase_questions` creates `QUESTION` / `ANSWERED`; an answer launches the next session
  member with the accumulated Q&A.
- `/sase_plan` creates a `TALE`, `EPIC`, or legacy `PLAN` turn. Feedback launches a
  replanner, while approval follows the selected tale/epic/commit policy.
- Agent-side workflow HITL creates `HITL`; accept, edit, feedback, and rerun branches
  may launch a continuation, while rejection or an unconfigured terminal branch stops.
- Agent-side `sase launch request` creates `LAUNCH` and defaults to resuming the
  requester after approve, reject, timeout, or failure. The successor receives the gate
  outcome, feedback, typed dispatch result, requester identity, session/workspace
  context, and checkpoint. A stopped gate remains terminal; an explicit
  `terminal_handoff` mode suppresses requester continuation on every branch.
- Agent-side `sase sudo request` creates `SUDO`. Approval settles it as `SUDOED` and
  launches the request's `next.prompt` successor with the runner ledger; denial settles
  it as `DENIED` without a follow-up. See [Sudo Requests](sudo.md).

For a custom handoff, pass `--turn` to `sase gate create`. `--next` supplies the default
answered-branch prompt; `--next-fork session|turn|none`, `--next-model`, and repeatable
`--next-output none|results|tail|file` control its context, model, and output channels.
The retired shell spellings still work: `--shell`, `--shell-status`,
`--shell-stop-status`, and the `--next-fork` shell value on `sase gate create`; a gate
spec's `"shell"` block, the `"fork"` key set to `"shell"`, and
`"continuation_mode": "gate_shell"`; and `--shell` on `sase proc list` or
`sase proc run` (where `--name` replaces it). Use the turn spellings for gates and
`--name` for proc commands. Stored records still read. Supplying both names for the same
option or block is an error. See
[feature_flags](../config/feature-flags.md#featureflags).

Branch policy in the specification may override or suppress that default. A turn block
without an explicit `continuation_mode` records the derived `gate_turn` mode; pairing a
turn block with an explicit `"none"` is rejected, because `"none"` would discard the
turn and leave the gate without a row in `sase gate list`. Selected option IDs joined
with `+` in query order form the answered branch key. Timeout, stopped, failed, and lost
branches never inherit the answered default: they launch only when explicitly
configured.

Answering a turn-backed gate runs its commands in a supervised detached proc by default,
so they survive the client that submitted the decision; `sase gate answer --no-detach`
opts into inline execution. Use `sase gate list` for pending turns,
`sase gate list --all` for their history, `sase gate show <turn>` for the resolved
branches and follow-up disposition, and `sase gate cancel <turn>` to settle a pending
turn without a follow-up. Approval history keeps its decision label (`TALE APPROVED` and
similar); that label does not imply the coder is running. A failed or interrupted
handoff is shown as needing attention with the
`sase gate answer --kind <kind> --id <id> --option ... --resume` recovery command. An
agent that creates a gate turn must end its turn rather than call `sase gate wait`;
direct waiting remains available to non-agent scripts.

### Gate inputs

An option's command reads its input as **stdin JSON**, never as command arguments —
templating reviewer-supplied values into `argv` would break the hashed-command trust
model, so there is no "extra args" escape hatch. An option declares what it needs under
`inputs`, a closed, declarative vocabulary that compiles into the option's
`input_schema` at creation time. `input_schema` stays the single enforcement layer: the
executor validates the submitted value against the compiled schema, so a reader that
knows nothing about `inputs` still enforces correctly.

```json
{
  "id": "restart",
  "label": "Restart service",
  "command": { "argv": ["commands/restart"] },
  "feedback": "optional",
  "inputs": [
    {
      "id": "target_env",
      "label": "Environment",
      "type": "enum",
      "required": true,
      "choices": ["staging", "production"]
    },
    { "id": "delay_seconds", "label": "Delay (seconds)", "type": "int", "default": 0 },
    { "id": "api_token", "label": "API token", "type": "line", "secret": true }
  ]
}
```

Each field has an `id` (the JSON property name, `^[a-z][a-z0-9_]*$`), a `label`, and a
`type`:

| `type`  | Compiles to                                 |
| ------- | ------------------------------------------- |
| `word`  | Non-empty string with no whitespace         |
| `line`  | String with no newlines                     |
| `text`  | Any string                                  |
| `path`  | Non-empty single-line string                |
| `agent` | Same as `word`                              |
| `int`   | Integer                                     |
| `bool`  | Boolean                                     |
| `float` | Number                                      |
| `enum`  | One of a declared, non-empty `choices` list |

`repeatable: true` wraps the compiled fragment in a JSON array. `choices` accepts either
plain strings or `{value, label}` objects and is required (and only valid) for `enum`.
`default`, `placeholder`, and `help` are optional; a declared `default` is validated
against the field's own compiled fragment, so a default no client could submit is a
creation error rather than a gate that fails on first answer. `secret: true` reaches the
command's stdin unredacted but is written to `response.json` and the execution journal
as `{"$redacted": true}` — masked display alone would not be enough, since the response
file is durable audit data. That covers every place those two files hold the value:
`option_inputs`, the legacy shared `input` beside it, and the stored command result. A
command is free to echo its stdin back, so any result string that merely _contains_ a
submitted secret is replaced whole rather than spliced. Only non-empty string secrets
are matched, because a secret boolean or small integer carries no entropy and matching
on it would redact unrelated output. The journal's `result_digest` is taken from the raw
result and still identifies exactly what the command returned.

`inputs` and a raw `input_schema` are mutually exclusive per option: declaring both is a
creation error unless the raw schema exactly equals what `inputs` would compile to. An
option declaring neither means "this command takes no input", which compiles to the
honest `{"type": "object", "additionalProperties": false}` schema; an author who
genuinely wants the permissive schema writes `"input_schema": {}` explicitly. A declared
`format` keyword is annotation-only — the executor validates with no `FormatChecker` —
so it is documentation, never a constraint. Every stored schema is pinned to the Draft
2020-12 dialect.

At creation, every option's effective schema is checked for **answerability**: SASE
builds the richest value a client could actually submit and checks that the schema can
accept it. For an option declaring `inputs`, that value is `{}` plus every declared
field's default plus `feedback` when the option's feedback mode allows it, validated
against the compiled schema. For an option declaring a raw `input_schema` and no
`inputs`, the reviewer types the value into a raw-schema editor — sase's TUI input panel
(one YAML editor under that option's section), `sase gate answer --option-input`, or the
mobile bridge's `option_inputs` — so every property declared under `properties` is
producible and the schema's own constraints on those properties (patterns, bounds,
types) are the reviewer's to satisfy. What still fails closed is a `required` name that
nothing renders a control for: a name absent from `properties`, or `feedback` on an
option whose feedback mode is `disabled`. An option that could never be answered by any
surface fails `sase gate create` with `unanswerable_option`, naming the offending
required property, instead of being accepted and dying silently on first submission.
Every input value is also bounded, both at creation and at submission: canonical JSON at
most 64 KiB, nesting depth at most 16, at most 128 properties in one object, and at most
512 items in one array.

sase's TUI collects typed values in that input panel. Each selected option that declares
`inputs` or a raw schema gets its own section, headed by that option's icon and label.
When two selected AND options declare the same field id compatibly, the field is
collected once — it renders in the first declaring option's section, annotated
`also sent to` the other option's label — and `option_inputs` still carries the value
under every option that declared the id. An incompatible duplicate blocks submit and the
panel shows the conflict. Confirming the panel always submits; cancelling never does,
and the next open of the same selection restores the draft. Every freeform box in the
panel is a vim editor (insert and normal modes). Tab and Shift+Tab walk the fields;
Ctrl+S submits; a `path` field also accepts Ctrl+T to cycle filesystem completions. The
reviewer note editor also offers next-word autosuggest from typed prompt history:
`Ctrl+T` takes one word, `Ctrl+L` takes all, and a mid-sentence guess appears as a
border peek rather than inline ghost text.

**Feedback is one rule everywhere.** The reviewer's free-text note is injected as
`input.feedback` for a selected option **iff that option's effective `input_schema`
declares a `feedback` property** — an option with no `feedback` property is left alone,
and an option with an ordinary `feedback` field declared under its own `inputs` is
respected as-is. The same rule runs inside the shared executor for every caller — sase's
TUI, mobile, Telegram, and `sase gate answer` alike — so a gate answers identically
regardless of where it was tapped.

**Submission is per option.** A surface submits `option_inputs`, a mapping of selected
option id to that option's own JSON value; a two-member AND branch can hand each member
a different value without either schema having to tolerate the other's fields. The
legacy shared-value contract (`input_data`, one JSON value applied to every selected
option) still works for bundles that predate per-option submission; the two are mutually
exclusive, and supplying both is a creation-time `conflicting_input` error.
`response.json` always records `option_inputs` (every entry is the same value under the
legacy path) alongside the existing `input` field, so nothing that reads `input` today
breaks.

### Gate actions

A gate action is a control the reviewer may run **as many times as they need** and that
**never answers the gate** — it exists so a reviewer can iterate toward a decision (edit
the plan until it validates, read a diff, run a dry run) instead of being forced to
answer or cancel immediately. Actions are declared in the request's `operations` array
(the field name that predates this mechanism, kept for wire compatibility) and rendered
in an **Actions** section, kept visually distinct from and above **Decision**; the
section is omitted entirely when a gate declares no actions.

Two kinds are declared:

- **`edit_file`** opens an editable resource in `$EDITOR`. `edit_target: "resource"`
  (the default) edits the bundle's own copy, exactly as before. `edit_target: "origin"`
  instead opens the durable file the resource was copied from — for example, a plan or
  epic gate's `edit_plan` action opens the file under `~/.sase/plans/` that
  `sase plan propose` wrote, not the bundle's snapshot of it. The edit is copied into
  the bundle and accepted only when the kind adapter validates it (for plan and epic
  gates, only when `sase plan validate` passes); on rejection the bundle keeps its last
  accepted revision and the reviewer's draft stays in the origin file rather than being
  discarded, so reopening the editor resumes their work. **While an origin file holds an
  edit the gate never accepted, every submit control is disabled — including reject —**
  and the surface shows a banner naming the file; discarding the draft (a separate,
  confirmed action) restores the origin from the last accepted revision.
- **`run_command`** runs an owned bundle command and shows the reviewer its output. Its
  stdout must be one JSON value validated against the action's own `result_schema`; the
  surface reads a small closed display record out of it — `summary` (a one-line toast),
  `body` (rendered per the declared `display`: `markdown`, `text`, `json`, or `none`),
  and `refresh` (whether the surface should reload and re-verify the bundle before
  re-rendering) — and everything else stays in the result and the execution journal.
  `targets` lists the editable resources the command is allowed to rewrite; after the
  command exits every resource is re-hashed, and a change to any resource **not** listed
  in `targets` is a `hash_mismatch` failure. This is what stops a display command from
  quietly rewriting the very command the reviewer is about to approve.

An action never writes `response.json` and refuses to run once the gate already has a
response or a cancellation. Every run — successful or failed — appends to the bundle's
execution journal (`journal.jsonl`), which is also what `sase gate wait --json` reports
under `operations`: the audit trail of what a reviewer ran before deciding.

An action may declare a single-character `key` (for example `key: "e"` on the plan and
epic `edit_plan` action). Creation rejects a key already reserved by the static gate
modal bindings (`q`, `d`, `g`, `G`, and the digit branch selectors `1`-`9`) or reused by
another action on the same gate. A collision with the reviewer's own configured gate
modal keymaps cannot be known at creation time; sase's TUI resolves it at render time by
reassigning from a deterministic fallback pool and displaying whichever key it actually
bound.

### Debugging a gate

Press `d` on any notification row or from an open plan, epic, question, launch,
custom-gate, or workflow HITL panel to open **Gate Debug**. The sudo review modal is the
exception: there `d` denies the request, so open Gate Debug from the notification row.
The overlay keeps the underlying form mounted, so closing it returns to the same
selected branch, checked group options, and typed feedback. Non-gate inbox rows use the
same view and show an explicit no-bundle state alongside their raw notification JSON.

Gate Debug loads bundle I/O and hash verification away from the TUI event loop. Its tabs
show the lifecycle overview, the canonical `request.json`, the terminal `response.json`
or `cancellation.json`, bounded execution error records, and the raw row from
`notifications.jsonl`. The overview re-verifies request and resource hashes live and
includes timeout, pending-action transport/staleness, and notification state. Missing,
malformed, or oversized artifacts render as diagnostics instead of preventing the modal
from opening.

| Key                 | Gate Debug action                                             |
| ------------------- | ------------------------------------------------------------- |
| `[` / `]`           | Switch tabs                                                   |
| `j` / `k`           | Scroll one line                                               |
| `Ctrl+D` / `Ctrl+U` | Scroll half a page                                            |
| `g` / `G`           | Jump to the top / bottom                                      |
| `y`                 | Copy the current tab's raw text                               |
| `Y`                 | Copy the gate bundle path                                     |
| `e`                 | Open the current tab's backing artifact in `$EDITOR`          |
| `d` / `Esc` / `q`   | Close Gate Debug and return to the underlying notification UI |

### Compatibility window

Readers resolve the neutral bundle first and then fall back to in-flight legacy plan,
question, launch, or HITL request directories. New producers do not dual-write the old
trees. Keep these fallbacks for at least one complete SASE release after neutral writers
ship and beyond the 24-hour remote-action stale window. The cross-kind resolver
regression test locks this rule in; removing a fallback requires a separately announced
migration after that window, updated fixtures, and explicit release notes.

Unanswered schema-v2 neutral bundles also remain hash-verifiable and answerable. Readers
project their historical first branch as the primary action in memory; new gate creation
requires schema v3 and an explicit `primary_branch`.

Question summaries use the same resolver, so sase's TUI can render both neutral and
legacy questions. Gate command execution from sase's TUI is scheduled as tracked
background work rather than running on Textual's event loop.

## Related

- [Notifications](notifications.md)
- [Notification types](notification-types.md)
