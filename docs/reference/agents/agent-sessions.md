---
title: Agent sessions
description: Look up sequential agent sessions and their shared history.
---

# Agent sessions

This page describes the sequential session model and how related agent turns are shown.

SASE uses three kinds of agent grouping. The
[directive reference](../macros/directives.md) documents their prompt syntax.

| Group             | Purpose                                                              |
| ----------------- | -------------------------------------------------------------------- |
| **Agent clan**    | A named, rootless container for parallel agents                      |
| **Agent session** | A strictly sequential chain named `<session>--<suffix>`              |
| **Agent tribe**   | A user-managed label displayed with an `@` prefix, such as `@review` |

Dot-separated names also define an agent _hood_: `foo.bar` and `foo.baz` are neighbors
in hood `foo`, and the agent named `foo` belongs to hood `foo` as well. A deeper name
belongs to every hood along its dotted path, so sase's TUI can group `foo.bar.worker`
with peers under `foo.bar` and cousins under `foo`. A session joins hoods under its bare
session name, not its root member's `--` name, so a session `foo` and a single agent
`foo.bar` are related in both directions exactly as two single agents with those names
would be. Clans use that namespace rule deliberately, while dotted names alone do not
create clan or session membership.

## Sequential Agent Sessions

An agent session is a strictly sequential chain. A session is created only when
`%i(suffix, session=parent)` attaches the first follow-up to an existing agent. At that
point SASE renames the original agent with its own `--<role>` suffix and reserves the
bare base name as a pure session container. Generic originals become `<session>--0`;
plan proposers use `<session>--plan`. Because creation requires an attachment, a session
always has at least two members.

For example, attaching a reviewer to agent `foo` creates session `foo`, renames the
original to `foo--0`, and names the new member `foo--reviewer`:

```text
%i(reviewer, session=foo) Review the diff produced by this session.
%i(tester, session=foo) Run the focused tests and report any failures.
%i(@, session=planner) #with_feedback:: Add failure handling before coding.
```

The positional suffix is a bare token: write `%i(reviewer, session=foo)`, not
`%i(--reviewer, session=foo)`. `%i(@, session=foo)` allocates the next free numeric
suffix.

Every session member has an `agent_session_role` derived from its suffix:

| Suffix                                         | Role                           | Display behavior                 |
| ---------------------------------------------- | ------------------------------ | -------------------------------- |
| `plan`, `code`, `epic`, `commit`               | Corresponding built-in role    | Built-in plan-chain status rules |
| Numeric (`@` allocates the next free number)   | Feedback or question round     | Built-in round status rules      |
| Any other word (`reviewer`, `tester`, `audit`) | The suffix itself, an open set | Ordinary RUNNING/DONE statuses   |

Arbitrary suffixes are ordinary session labels, not configured lifecycle hooks. SASE
does not discover or execute custom `kind: agent_session` definitions. Replace a stale
definition with an explicit session attachment or an agent-requested launch.

An agent turn is the assistant speaking, a monitor turn is a tool result arriving, and a
gate turn is the human's move.

A `--mon` suffix (and `--mon-0`, `--mon-1`, … for later members in the same session) is
a **monitor turn**: a session member whose work is one supervised OS command instead of
an LLM turn, created by `sase monitor start`. See [Monitors](../automation/monitors.md).

A `--gate` suffix (then `--gate-0`, `--gate-1`, …) is a **gate turn**: a named, non-LLM
session member that owns a durable user decision. The asking agent ends its turn, the
pending gate occupies no runner slot and contributes no accumulated session or clan
runtime, and the turn settles after the decision's commands complete. It can retain or
release the workspace claim according to its claim policy. An answered branch may launch
the next agent-turn member; timeout, stop, failure, and loss do so only when that branch
explicitly declares a follow-up. The built-in question, plan, workflow HITL, and
agent-initiated launch flows use this model, as can custom `sase gate create --turn`
requests. See
[Command-backed interaction gates](../automation/notification-gates.md#command-backed-interaction-gates-1).

`sase pipe '<prompt>'` creates a session member the same way a plan approval or a
question follow-up does: it ends the calling agent's turn in-process and continues the
run as the next member, in the same workspace and claim. The successor gets the next
free numeric suffix (role `feedback`) by default, or an explicit `--name TOKEN` suffix
(role: the token itself), per the suffix table above. Every host-composed successor
inherits autonomy structurally from its predecessor's live record; an explicit `%auto`
in agent-authored follow-up text can only narrow. See
[Monitors: Pipe vs. monitor](../automation/monitor-operations.md#pipe-vs-monitor).

SASE resolves `parent` to the newest visible matching agent or session member in the
current project. If the parent is still running, the new member appears immediately as
WAITING and starts only after that exact parent artifact completes successfully. If the
parent fails, stops, or is killed, the queued member becomes STOPPED and SASE sends a
completion notification.

If the parent is missing, ambiguous, or dismissed, or the composed member name already
exists, launch preparation fails before spawning the member. Collision errors suggest
`%i(@, session=parent)`. `%wait:<session>` and `#fork` references to the bare session
name resolve through the session container; `sase agent wait <session>` uses the same
session target and waits for successors that appear after the wait begins. A bare name
also covers an agent that becomes a session after the fork or wait was bound: a fork
bound while the parent is still a plain agent stays waiting through review and coding
once that parent is promoted into a session. An exact `--<suffix>` name targets one
member. A member attached to an agent already inside a clan inherits that clan
membership.

A monitor or gate turn that ended unsuccessfully without handing off to a follow-up
member normally keeps a bare-session wait blocked. Retries are the exception: when the
same session generation (the newest root plus its attached members) also contains a
newer turn of the same kind, SASE ignores the older failed turn while resolving the bare
session name. For example, if `--mon` fails to start and `--mon-0` takes over, the
session wait follows `--mon-0` and the other members instead of staying blocked on
`--mon`. The newer turn only replaces the older failure; it still has to finish
successfully (or hand off) before the session can settle. Kinds never mix: a newer gate
does not excuse a failed monitor, or vice versa. An exact wait on the old turn's full
name still reports that turn's own failed outcome. A session member that has crossed its
own dependency waits and is only queued for a runner slot is still a live member, so
bare-session `%wait` and `#fork` targets stay blocked until it finishes. Members still
parked on their own dependency waits stay out of the session aggregate so sibling waits
cannot deadlock. A failed turn that handed off to a follow-up does not release a `#fork`
wait while that follow-up is still pending.

`%wait` uses the same session and turn vocabulary. `%wait:<session>` and
`%wait(session)` wait for the whole generation. `%wait(session, target=turn)` captures
the current turn when the wait is bound — a pending gate if the session is parked there
— and releases when that turn settles. See
[Launch directives](../macros/directive-launch.md) for the `%wait` keyword contract,
including the epic-follow interaction.

`#fork:<session>` contributes every known concrete turn — agent, monitor, and gate turns
alike — in chain order, oldest first, including turns that ended unsuccessfully with
their recorded failure context. Only a turn that is still running, or whose transcript
or log is missing or unreadable, is listed as not shown rather than injected. Shared
inherited history is de-duplicated across the included agent-turn transcripts. When a
session member forks its own session, that member is omitted from both the shown and
not-shown member lists. At least one shown member is required. Use
`#fork:<session>--<suffix>` when only one member should be a parent — this also accepts
a monitor's `--mon`/`--mon-N` suffix, and a monitor's exact durable proc ID is always
the unambiguous choice if its reusable proc name is ever reused. A session container can
also be combined with independent agent, proc/monitor, session, clan, or tribe parents
in one multi-parent fork.

Fork history follows the wait record captured when the fork was bound. A session target
selects the generation by its root artifact identity, so a later session with the same
name cannot replace it. A turn target on a bare session name includes the session
through the pinned turn; later turns appear under **Not shown** with the reason “after
the bound turn.” An exact member target includes that member alone. Use
`#fork(<session>, target=turn)` to wait for and include the current turn captured at
launch. If the session is parked at its gate, this waits for the gate decision; use
`#fork:<session>--plan` to fork the plan immediately.

### Session detail folding

Selecting a real multi-member session root in sase's TUI opens the Main deck with
underlined `SESSION` (cyan, matching the name), with a numbered `SESSION TURNS` roster
in the jump panel in stable chain order: agent turns in chain order, with each monitor
spliced in directly after its starter turn. The original member and each follow-up are
direct jump targets; synthetic planner projections and parallel-family scaffolding are
not. The roster follows the global panel fold keys (`zz`, `zZ`, and the direct level
keys); the root's foldable output variables, workflow variables, SASE context, slow
calls, and errors use the same chords plus `za`/`zA`.

Session summaries have two effective levels. Level 1 shows bounded activity, wait/retry,
context, and compact member metadata; level 2 adds full foldable metadata plus member
workspace, timestamp, and attempt annotations (roster annotations show when the jump
panel is expanded with `.`). Press `zZ` at level 1 to open every fold to level 2, or at
level 2 to close every fold to level 1. Press `z1` or `z2` to select either level
directly. `z3` and `z4` are invalid in a session context and leave both the panel level
and section overrides untouched. A member-specific override inherits from the
`SESSION TURNS` section, which in turn inherits the panel level; any leftover roster
override still applies until a global fold key clears overrides. The numbered roster and
its digit jumps remain present at both effective levels.

The session root's `SLOW TOOL CALLS` section also follows that two-position scale. Level
1 keeps one aligned row per call with a short target digest and a tail explaining that
full commands are hidden. Level 2 retains those rows and adds the wrapped full command
or target, timing and outcome facts, errors, output previews, subagent statistics, and
relative slow-time rank beneath each call.

`AGENT PROMPT` and the consolidated `AGENT REPLY` are always shown in full at both
session levels, without fold glyphs or section overrides. They remain navigation anchors
for `Ctrl+J`/`Ctrl+K`; `za` and `zA` skip them without changing the override registry.
The session's `AGENT MACRO` renders in the sticky header panel above the data deck (a
collapsed preview, or in full after `d`) rather than in the body. Absent macro and
prompt sections are omitted, while reply rows for members that have not responded yet
remain visible with their pending state.

A session root is a sase agent, so its jump panel also carries a `NEIGHBORS` section
listing the sase agent's ancestors, descendants, and hood neighbors; it sits after
`SESSION TURNS` when both exist. The session participates under its bare session name
rather than the root member's `--` name, so a session `fam` lists `fam.helper` as a
descendant and `fam.helper` lists `fam` back as its ancestor. Both rosters draw their
digits from one continuous ladder, so session members are numbered first and neighbors
after, with a single shared number width. Session members already shown under
`SESSION TURNS` are never repeated in `NEIGHBORS`; they are reported as a dim
`… +N also listed under SESSION TURNS` tail. Every neighbor is always listed and
numbered after the session members, whatever the fold level. See
[Sase Agent Neighbors Section](../tui/agents-tab-panels.md#sase-agent-neighbors-section)
for the full behavior, which single agents share through their own three-level scale.

#### Session member detail folding

Selecting a session **turn** row — not the container — also renders a numbered
`SESSION TURNS` roster in the jump panel: every turn of the enclosing session in the
same stable chain order, except the selected turn itself, numbered starting from `0`.
The heading carries a dim ` · <session name>` suffix naming the session. Digit jumps
behave exactly as they do on the container roster — `0`–`9` (or two-key `00`–`99` past
ten turns) reveal the target turn, and a roster that changed since the panel was drawn
cancels the jump with a warning instead of landing somewhere stale.

Unlike the container's two-level session scale, a member panel folds every other section
on the selected member's own three-level agent scale (`z1`–`z3`, `zz`, `za`, `zA`),
while its jump-panel roster follows the global panel fold keys, so no `Fold: N/M` header
line appears. A member row is an agent turn node rather than a sase agent, so its panel
names that with underlined `AGENT TURN` (gold, matching the name), has no `NEIGHBORS`
section, and shows only `SESSION TURNS` for the enclosing session. The container panel
names itself `SESSION`.

#### Per-member model lanes

A session container has no single model: `%m` overrides, provider defaults, and
per-member reasoning effort can differ along the chain, and one shared `Model:` line
would hide that. So when a session projects to two or more concrete members, the
`Model:` field in the session root's detail-panel header expands into one lane per
member instead of a single value:

```text
Model:  --plan    · CLAUDE(opus) @ high ← @large
        --code    · CODEX(gpt-5.1-codex) ← @medium
        --review  · default
```

Each lane's value uses the same `PROVIDER(model) @ <effort> ← @<alias>` rendering as
every other SASE surface — the single-agent panel and `sase agent show` included — so
one reading habit covers all of them. The `← @<alias>` chip appears only when the member
was launched with an `@` model alias, and it is launch-time provenance: completed runs
keep showing the alias that launched them even if that alias is later retargeted or
deleted. Member labels are the `--<suffix>` labels from the `SESSION TURNS` roster,
padded to one aligned value column, and a member with no recorded model renders a dim
`default`. Long values wrap beneath that column rather than pushing the layout wide. At
most 12 lanes are shown; a larger session adds a dim
`… +N more turns (see SESSION TURNS)` tail. The lanes are not part of the two-level fold
scale — they read the same at level 1 and level 2. A session that projects to fewer than
two concrete members, and every ordinary single agent, keeps the original one-line
`Model:` field.

Two bundled macros help assemble common follow-up prompt bodies. They build text only;
`%i` performs the attachment:

```text
%i(@, session=planner) #with_feedback:: Add failure handling before coding.
%i(@, session=planner) #with_q_and_a(qa_file=/tmp/qa_rounds.json):: Continue with the base prompt.
```

The full directive grammar is documented under
[Macro directives](../macros/directive-syntax.md#supported-directives).

### Attaching within a multi-agent prompt

A later segment can attach to a statically named parent from an earlier segment:

```text
%i:foo Plan the change.
---
%i(reviewer, session=foo) Review foo's plan.
```

The attached member waits for the in-batch parent to complete successfully. This lookup
supports earlier static names such as `%i:foo` or `%i(foo)`; template-named and
auto-named parents must already have an artifact before they can be used as attachment
targets.

### Sase Agents, Sessions, and Commit Provenance

A sase agent is either a session or a single agent that does not belong to one. Commit
provenance is anchored on the sase agent, not on the concrete turn that happened to be
running: a commit by `fam--code` is tagged `SASE_AGENT=<username>.<machine>.fam` and
links to `sessions/<username>.<machine>.fam.md` with no member anchor, while a solo
agent's footer is exactly what it has always been. The same projection is used for the
sidecar publication identity and for the agent rows on plan headers and bead pages, so a
session appears once as itself instead of once per member.

The practical consequence is that the **session page is the durable home of a session's
commits**. Members come and go — a member's artifact can be cleaned up long before the
session is done — but the sase agent outlives them, so its commit history is carried on
the session container and rendered on the session page, with member-attributed rows
keeping their role and sase-agent-level rows showing `—`. Commits made before this
change name a concrete member and are still read that way forever; nothing is rewritten.
See
[runtime provenance](../../contribute/commit-workflow-orchestrator.md#cli-inputs-and-internal-payload)
and [browsing page anatomy](hood-sync.md#browsing-page-anatomy).

## Related

- [Agents and workspaces](index.md) — the section hub.

## `sase agent`

`sase agent` provides cross-project visibility into running agents and synchronizes
shared agent history. Subcommands:

<a id="cli-options-48"></a> Moved to [sase agent](agent-sessions.md#sase-agent).

<a id="command-behavior-32"></a> Moved to
[Agent sessions](agent-sessions.md#command-behavior-32).

## Command behavior {#command-behavior-32}

Agent-index paths default to `~/.sase/agent_artifact_index.sqlite` and
`~/.sase/projects`. `sase agent index vacuum` is a dry run unless `-a`/`--apply` is
supplied. It reports freelist pages left by normal SQLite deletes and dismissed-identity
row counts. Apply runs SQLite `VACUUM` to rebuild the index file and reclaim that free
space; it never removes or alters an index row. `-i/--index-path` selects another index
and `-j/--json` emits the machine-readable report.

`sase agent persist-cleanup`, `sase agent persist-directive`, and `sase agent revert`
are durable-operation entrypoints that sase's TUI runs as procs; they read their details
from the `-Q/--request-path` sidecar and are not meant for direct use.

## `sase agent wait`

`sase agent wait NAME ...` resolves each target the same way `%wait` does: clan, then
agent session, then workflow, then exact agent name. A session target waits on the whole
session, including successors that appear after the wait begins.
`-T/--target session|turn` selects that scope: `session` (the default) keeps this
whole-session behavior; `turn` pins each NAME's current turn at invocation through the
shared wait binder and then waits on that single member. JSON output includes the bound
`turn_name`. Clans and workflows reject `turn` with the same core message as
`%wait(..., target=turn)`. `-a/--all` stays session-scoped and cannot be combined with
`-T turn`. `sase agent wait -a` waits for every eligible agent running at command start
and deliberately does not absorb later unrelated launches; when run from inside an agent
it excludes the calling agent's own session so `-a` cannot wait on itself.
`-p/--project` scopes target resolution and the `--all` snapshot to one project.

By default the command stops when a target cannot progress without a human: a pending
question, a submitted plan awaiting review, or a stopped artifact with no completion
marker exits `3`. Use `-w/--wait-blocked` only when you want the gate to keep polling
through those states. `-t/--timeout` exits `4` if unfinished targets remain after the
duration, and `-i/--interval` pins the poll interval instead of using the adaptive
default.

Exit codes are `0` when every target succeeded, `1` when any target finished
unsuccessfully, `2` for command usage or resolution errors, `3` for human-blocked
targets without `-w`, `4` for timeout, and `130`/`143` for `SIGINT`/`SIGTERM`.
Precedence is `1 > 3 > 4` when more than one condition applies.

Progress output goes to stderr. The final settle summary goes to stdout, and `-j/--json`
prints one stdout JSON envelope with no progress noise, so gate JSON and command
substitution both stay predictable.

`sase agent list -j` reports every live runner-slot waiter as `status: "QUEUED"`,
whether it is waiting on the global budget or an authored `%queue(capacity=N)`
weighted-load threshold. Its `queue_weight` reports requested capacity units, and
`runner_slot_queue_position`/`runner_slot_queue_size` rank the same waiters in the
capacity-aware display order used by sase's TUI: eligible waiters first, then parked
waiters by current blocker severity, with priority and request FIFO preserved inside
each group. A waiter parked by an [agent hold](agent-holds.md#sase-agent-hold) also
reports the blocking hold's armer in `held_by` and that hold's expiry in
`hold_expires_at`. Each entry also exports the epic-follow state: `wait_for_epics_of`
(armed follow targets) and `epic_follows` (per-target `launching` / `following` /
`blocked` stages with `epic_ids`, `added_bead_ids`, and blocker details).
`sase agent wait` rows use the same shared phrasing (`↪ waits on <target>'s epic <id>`)
as the TUI lanes.
