---
title: Launch directives
description: Directives for agent identity, launch settings, and queue admission.
---

# Launch directives

This page documents directives that set agent identity, launch settings, and queue admission.

## Agent Names, Waits, and Queue Admission

The `%id` and `%wait` directives can be used without arguments. Bare `%id`
auto-generates a permanent unique name for the agent. `%id(<id>, clan=<clan>)` derives
the full `<clan>.<id>` name and requests membership in that clan. Dotted ids are
allowed, and a leading `!` forces reuse of the derived name. `%id(<id>, tribe=<tribe>)`
tags an explicit id, while `%id(tribe=<tribe>)` and `#tribe:<tribe>` tag an auto-named
agent. The `clan=`, `session=`, and `tribe=` keywords are mutually exclusive, and none
can be combined with a `%clan` declaration in the same prompt. Bare `%wait` resolves to
the most recently named agent (raises an error if no previous agent exists).

Agent-name templates contain exactly one marker: either the bare `@` marker or a keyed
marker written `{@<id>}` or `{@<id>!}`. The marker is not a wildcard; SASE replaces it
with the next token from the shared auto-name sequence (`0`, `1`, ..., `9`, `a`, ...,
`z`, `00`, ...). The `<id>` in a keyed marker is one or more alphanumeric segments
joined by dots, such as `{@1}`, `{@research}`, or `{@lead.a}`. A single agent-name value
cannot contain multiple markers or mix a braced marker with a stray bare `@`.

For bare templates, with no reserved names, `%id:@.cld` renders as `0.cld`,
`%id:build-@` renders as `build-0`, and `%id:research.@.final` renders as
`research.0.final`; `%id(cld, clan=research.@)` derives that same `research.@.cld`
template before allocation. The older terminal `-@` form still works, but new
allocations now start at token `0` and use the alphanumeric sequence instead of positive
integers. Later `%wait`, `#fork`, and `#resume` references can use the same template
text; in one multi-agent launch, SASE rewrites those references to the concrete name
already planned for that template before spawning dependent agents.

Keyed markers resolve once per dispatch before directives are extracted or agent
processes spawn. On the typed-admission path that resolution happens when the immutable
launch plan is created — across the complete expanded batch, before it is split into
durable logical units — so later admission and coordinator restarts reuse the planned
tokens. Every occurrence of the same key in the prompt text gets the same concrete
token, including `%id`, `%clan`, `clan=`, `%wait`, `#fork`, `#resume`, and ordinary
prose references such as `research.{@1}.cdx`. The same separator rule as bare templates
applies: with token `o`, `research.{@1!}` becomes `research.o`, `foo{@1!}` becomes
`foo-o`, and a marker at the start of a line becomes `o`.

Inside a macro swarm, unqualified keyed markers are implicitly qualified to
`{@<macro>.<stamp>.<id>!}` while the swarm expands. That qualification gives each swarm
invocation its own key space, even when the same swarm is invoked more than once in one
dispatch. Keys are dispatch-scoped: a later `sase run` or TUI launch allocates fresh
tokens rather than reusing a previous dispatch's table. A trailing `!` means "already
qualified" and suppresses the implicit `<macro>.<stamp>.` prefix; use it only when a
caller and a nested swarm must deliberately share one hood, for example `{@shared!}` in
both bodies. Outside macro swarm expansion, an unqualified keyed marker in a literal
prompt or plain inline macro resolves with its literal id, as if it had been written
with `!`.

The bare `@` marker remains supported, and references to a bare template keep the
latest-wins behavior. That is unsafe for macro swarms whose
members can start late, because a later swarm launch can become the latest matching hood
before a deferred member boots. Use keyed markers in macro swarms whenever several
segments, waits, clan references, or prose references need the same generated name.

Agent names are permanent IDs. A name that belongs to any existing agent state cannot be
reused by a normal `%id:<name>` launch; SASE cancels the launch before spawning an
agent, records the prompt as cancelled, and suggests the lowest free numeric suffix such
as `<name>1`. To deliberately reuse a name, use `%id:!<name>` from the TUI; the `!` form
is the explicit confirmation to wipe the previous owner and its persisted system state
before launching the new agent with that name. Non-TUI launch surfaces reject
`%id:!<name>` unless they provide an explicit confirmation path.

The `%i(<suffix>, session=<parent>)` form attaches a new agent to a sequential session.
On the first attachment, SASE renames the original agent with its own `--<role>` suffix
and reserves the bare base name as a pure session container; generic originals become
`--0`, while plan proposers become `--plan`. SASE then names the new member
`<session-base>--<suffix>`, writes the normal session metadata, and strips the directive
before the model sees the prompt. The positional suffix is a bare token: write
`%i(reviewer, session=foo)`, not `%i(--reviewer, session=foo)`.

Reserved suffixes (`plan`, `code`, `epic`, `commit`) select their built-in session roles
and status labels. Numeric suffixes and `@` are feedback/Q&A rounds; `@` allocates the
next free suffix. Other alphanumeric suffixes such as `reviewer` or `tester` are
allowed, preserve that open-set role in `agent_session_role` metadata, and use ordinary
RUNNING/DONE status labels. See [Agent Clans, Sessions, and Tribes](../agents/index.md)
for attachment and agent-initiated launch behavior.

If the parent is still running, the new session member appears immediately as a WAITING
row and starts when that exact parent artifact completes successfully. If the parent
fails, is stopped, or is killed, the queued member is cancelled to `STOPPED` and SASE
sends a completion notification explaining the failed dependency. If the parent is
absent, ambiguous, dismissed, or the composed child name already exists, launch
preparation fails before spawning the child; collision errors suggest
`%i(@, session=parent)`.

The session-attach form works from every normal user launch surface because the
constraint check runs in shared launch preparation. In a multi-agent prompt,
`%i(suffix, session=parent)` may reference a parent explicitly named in an earlier `---`
segment of the same prompt, such as `%i:foo` followed by `%i(reviewer, session=foo)`.
The in-batch parent is treated as a running parent: the member queues as a WAITING child
and starts when that exact parent artifact completes successfully. This same-prompt
lookup is limited to earlier static names; template-named and auto-named parents still
require the parent artifact to exist before they can be used as
`%i(suffix, session=parent)` targets.

Named `%wait` dependencies unblock only after the newest matching agent run has a
`done.json` outcome of `"completed"`. For a clan name, every member of its newest
generation must complete successfully; for a session or multi-agent workflow name, every
member or child must complete successfully. An exact agent name still targets only that
agent. Failed, killed, crashed, still-running, malformed, or missing `done.json`
artifacts do not satisfy the wait; the dependent agent stays parked until a later
successful run of the same dependency name appears. When the dependency has already
ended unsuccessfully, AXE's `wait_checks` job posts one red `wait_checks` notification
("Wait dependency can never self-resolve") that names the waiter and the blocking
artifact and attaches both directories; later passes add `+1` evidence to the same row
instead of new notifications. If the blocker is a monitor whose follow-up could not
launch, the notification also names the `sase monitor resume <id>` command and any saved
worktree recovery diff. The waiter itself stays parked: kill and relaunch it, clear the
wait, or let a later successful run release it.

A bare session target makes one exception for retried turns. A monitor or gate member
that ended unsuccessfully without handing off to a follow-up is ignored once a newer
member of the same kind exists in the same session generation. A failed `--mon` or
`--gate` member does not block the session after `--mon-0` or `--gate-0` takes over.
This applies to every older failed turn of that kind; the newest turn then counts like
any other member and must itself succeed. A monitor never replaces a failed gate or vice
versa, and an exact turn-name wait such as `<session>--mon` still reports that turn's
own outcome. See
[Sequential Agent Sessions](../agents/agent-sessions.md#sequential-agent-sessions).

The repeatable `bead=<bead-id>` keyword adds a closure condition from the waiting
agent's own project bead store. Every named agent/artifact condition and every bead
condition must resolve before the wait releases; a missing bead, missing store, or read
error keeps the agent parked. For example, `%wait(build, bead=<bead-id>)` requires both
the successful `build` agent and the named bead to be closed. Multiple `bead=` values
preserve their authored order and are deduplicated. Bead-only waits do not name an
agent, so they do not participate in bare-wait rewriting, agent-name templates, or
cross-project lookup. Once a wait releases, reopening the bead does not re-park the
agent. Once the waiting agent is published, it is linked to every bead it waited on:
`wait_for_beads` projects `agent:<name> awaits bead:<id>` (while `%id(..., bead=<id>)`
yields `agent:<name> implements bead:<id>`).

The repeatable `hood=<hood-name>` keyword snapshots the hood members that already exist
when the waiter is launched and requires every current member to complete successfully.
Hood matching follows component boundaries, so `hood=research` matches `research` and
`research.worker` but not `researcher.worker`. For a reused member name, only its latest
run at or before the waiter's launch counts; members launched later do not extend the
wait. An empty hood resolves immediately with a diagnostic instead of parking forever.
Multiple `hood=` values are deduplicated in authored order and combine with agent, bead,
and time conditions.

Agent waits follow launched epics by default. `%wait(planner)` and `%wait:planner` first
wait for the target's successful completion, then require closure of the epics that
target launched. If the target launches no epic, the ordinary agent completion condition
is enough. An epic inherited as a worker's assignment does not count as an epic that
worker launched.

Use `for_epic=false` when you only need the agent's own result:

```text
%wait(planner)                                # Agent completion plus its launched epics
%wait(reviewer, for_epic=false)               # Reviewer completion only
%wait(build, for_epic=false, bead=<bead-id>)  # Agent completion plus this explicit bead
```

The policy applies to the agent targets in each `%wait` occurrence. Separate occurrences
can use different policies; an explicit value overrides the default for a repeated
target, while contradictory explicit values are an error. A `--plan` row always releases
at plan submission and never follows; explicit `for_epic=true` on that row is an error.
`for_epic=` also requires an agent target in the same occurrence and accepts only `true`
or `false`. The corresponding diagnostics are `wait-for-epic-plan-row`,
`wait-for-epic-without-agent`, `wait-for-epic-invalid-value`, and
`wait-for-epic-conflict`.

While an epic launch is in flight the waiter stays parked. Once the epic IDs are known,
SASE adds their closure conditions to the wait. A failed or skipped launch, a dismissed
launch target, or a dependency cycle can leave a blocked follow; AXE reports the
blocker, and the TUI shows it with a teal `↪` annotation. Use the
[Wait modal](../tui/agents-tab.md#wait-modal) to inspect or change the policy.
Generated epic phase and land schedules explicitly use `for_epic=false` alongside
phase-bead waits.

Existing persisted waits without `wait_for_epics_of` retain their older completion-only
behavior. This compatibility rule concerns saved wait state; omitting `for_epic=` in a
new prompt uses the new default. The policy is independent of tribe `@epic`.

An `@<tribe>` dependency has next-entity semantics. `%wait:@review` ignores older tribe
members and selects the earliest successfully completed eligible entity launched after
the waiting agent: one standalone agent or one whole clan generation. A tribe-assigned
clan member enrolls its generation, which becomes eligible only when the normal
aggregate clan wait succeeds. `#fork:@review` implies this same wait and then resumes
from the selected agent conversation or every member's launch-ordered prompt and reply
summary in the selected clan; full clan-member replies remain available through the
included transcript paths rather than being injected automatically. Tribe names use
letters, digits, underscores, dots, and dashes after the leading `@`. `@default` is
rejected because that panel is display-only, and `@job` targets AXE job agents (see
[The built-in job tribe](../agents/agent-tribes.md#the-built-in-job-tribe)).

A submitted plan awaiting review is the one exception. A planner that ran
`sase plan propose` blocks in the approval flow without writing a `done.json`, so its
planner row shows the `PLAN` status. A `%wait` on that planner row — its canonical
`<base>--plan` name or the accepted `<base>.plan` spelling — treats the submitted plan as
done and unblocks while the plan is still in review. This targets the planner row only:
a `%wait:<base>` on the bare session container stays parked until the whole plan chain
actually completes, so a submitted plan alone never makes the chain look finished.

When a launch has exactly one explicit `%wait:<name>` dependency and no explicit `%id`,
SASE can allocate a derived name before spawning the waiting agent: `<name>.w0`,
`<name>.w1`, and so on, using the first free template token. After `<name>.w9`,
letter-leading IDs gain a separator (`<name>.w-a`, `<name>.w-b`, and so on) to keep the
name readable. Multi-value waits, tribe targets, bare `%wait`, and prompts whose name
depends on unresolved macro expansion do not get a parent-side derived name. Repeat
launches reuse this rule, then chain later repeat slots with
`%wait:<previous-slot-name>`.

Fork/resume names follow the same sequence: `<name>.f0` through `<name>.f9`, then
`<name>.f-a`, `<name>.f-b`, and so on. Retries use `<name>.r0` through `<name>.r9`, then
`<name>.r-a`, `<name>.r-b`, and so on. If a prompt includes both `#fork`/`#resume` and
`%wait`, the fork-derived `.f@` template takes precedence over the wait-derived `.w@`
template. The wait still controls launch ordering, but the planned agent name follows
the resume/fork lineage. A tribe fork uses a neutral auto-name because the concrete
parent entity is deliberately unknown until its wait resolves.

The `%wait` directive also accepts a `time=` keyword to defer launch by a duration or
until an absolute wall-clock time. For a pure time wait, `#t:<time>` is shorthand for
`%wait(time=<time>)`.

- **Durations** in `XhYmZs` format (e.g., `%wait(time=5m)`, `%wait(time=1h30m)`,
  `%wait(time=90s)`, or `#t:5m`). When multiple `time=` durations are specified, the
  maximum is used.
- **`HHMM`** — wait until that time today (e.g., `%wait(time=1430)` for 14:30). If the
  time has already passed, it wraps to tomorrow.
- **`yymmdd/HHMM`** — wait until a specific date and time (e.g.,
  `%wait(time=260415/0900)` for 2026-04-15 at 09:00). Raises an error if the target is
  in the past.

Agent, bead, and hood dependencies and `time=` combine across `%wait(...)` directives.
`capacity=`, `priority=`/`p=`, and `weight=`/`w=` combine separately across
`%queue(...)` / `%q(...)` directives. All dependencies wait first, then the time floor
applies, and the runner-capacity gate is the final admission stage. That stage also
keeps a launch `QUEUED`, even with free capacity, while an active
[agent hold](#hold-directive) matches it. Primary and linked-workspace preparation
starts only after admission, so admitted capacity includes that preparation work.

The effective global `max_running_agents` value is an integer capacity budget
(configured default `10`; an active `~/.sase/max_running_agents_override.json` value
wins). A launch without an authored weight claims `1.0` unit. `%queue(weight=W)` /
`%q(w=W)` requests a non-negative finite capacity weight such as `0`, `0.25`, `1.0`,
`2`, `.25`, or `2.5e-1`; negative, boolean, NaN, infinity, overflow, and underflow to
zero are rejected. An authored zero is stored as `+0.0` and formats as `weight=0`. A
zero-weight agent adds no load while it runs but still takes its queue turn: it waits
only while the fleet is exactly full or over-committed. Omitted weight defaults to
`1.0`, but an explicitly authored `1.0` is preserved when prompts are reconstructed. `w`
and `weight` are one field, so using both is a duplicate even when the values match.

Admission requires occupied weighted load plus the requested weight to fit within this
launch's admission limit. Without an authored capacity, the limit is the current global
`max_running_agents` budget. `%queue:N`, `%q:N`, `%queue(N)`, and `%queue(capacity=N)`
replace that limit for this launch only: the agent starts when occupied weighted load
plus its own weight fits within the authored positive-integer budget. `%q:1.5x`,
`%q(1.5x, w=0.25)`, and `%q(capacity=.5x)` instead author a multiplier of the effective
`max_running_agents` budget. Multipliers have at most two decimal places (`2x`, `1.5x`,
and `1.25x` are all valid) and are re-resolved on every queued admission poll, so a
`1.5x` multiplier with effective budget `5` has an admission limit of `7.5`, then
becomes `15` if the effective budget rises to `10`. A weight above the resolved budget
stays `QUEUED` until the budget changes. This means `%q:100` can intentionally admit
work above a global budget of `1`, while `%q:1` is the run-alone barrier for a
default-weight launch. Four independent claims of weight `0.25` fit in capacity `1`; one
claim of weight `2` does not, so authoring weight greater than an integer capacity is
rejected. `capacity=0` is rejected at authoring time with a migration message
recommending `%q:1` for run-alone behavior. Authored `runners=` on `%queue` is rejected
with a migration message naming `capacity=`. `%wait(runners=...)` also recommends
`%queue(capacity=...)`. Stored `wait_runners` integer values load as `queue_capacity`.

Among waiters that currently fit their own admission limit, the lowest numeric
`%queue(priority=N)` / `%q(p=N)` starts first, with FIFO ordering among equal
priorities. That sort only compares waiters already parked when capacity frees, so a
waiter whose priority is numerically worse than the `10` default additionally holds back
for a bounded deference window. Default- and better-priority waiters (`priority=10` or
lower) never defer. The window is `min((priority - 10) * 3, 60)` seconds by default and
is configurable through
[`runner_slots`](../config/agents-and-runners.md#runnerslots). Deference is not
priority aging or preemption, and a steady stream of fitting higher-priority arrivals
can still starve lower-priority work.

A standalone agent owns one claim of its effective weight. A live serial session shares
one claim across its agent, monitor, and serial successor turns; serial continuations
inherit the session weight when their prompt omits one, and must reacquire capacity
after the session releases its claim. Independently launched clan members and live
parallel session members each hold their own claim. Processless gates and modern
question gate turns hold zero capacity while waiting for a human, and their follow-up
work must either transfer a live claim or re-enter admission. Once a decision arrives,
the gate turn makes one capacity attempt before running the chosen option's commands,
and that attempt never parks: if the gate's weight fits, it claims capacity so the
follow-up can inherit it; otherwise the commands run right away without a claim and the
follow-up queues normally. A gate that `%auto` resolves at creation time runs its
commands inside the creating agent's existing claim instead of taking a second one. The
Both the host-owned monitor that launches an approved epic and an agent-authored
`sase monitor start -w 0` pure-wait monitor record an explicit zero weight and consume no
capacity; the phase agents launched by the epic monitor claim their own. A zero weight
can also be authored with `%q(w=0)`: a user-authored zero is inherited by successors as
explicit, while a monitor's zero never leaks to them. A `%proc` unit with
queue fields is checked against this budget but never holds a claim (see
[Typed launch units](directive-syntax.md#typed-launch-units)). Workflow Python/bash steps and axe Patch
runners are outside this budget.

Roll out this change by replacing long-lived sase's TUI/AXE and runner processes, or by
letting old work drain before launching weighted workloads. Records written before
`queue_weight` existed remain readable as `1.0`; that compatibility is for storage, not
for safely mixing old admission binaries with new weighted scheduling.

Absolute time waits cannot be combined with duration waits or with each other.

Timed waits use `#t:<value>` or `%wait(time=<value>)`. Every positional `%wait` value is an agent or workflow name,
including time-shaped values such as `%wait:4h` and `%wait:1430`. Timed waits must use
`%wait(time=<value>)` or `#t:<value>`.

Multi-value directives (`%wait`, `%model`, `%alt`) accept comma-separated arguments to
collapse what would otherwise be several lines: `%wait:agent_a,agent_b` is equivalent to
two separate `%wait:` directives. Backtick-quoted values (e.g. `` %wait:`a,b` ``) are
treated as a single literal and not split on commas.

The `%hide` directive is a boolean flag — it takes no arguments and is simply present or
absent. The `%auto` directive covers both plan tiers when bare and accepts `:plan`,
`:tale`, `:epic`, `:manual`, or `:off`; any other value, and any parenthesized form,
fails at launch.

## Example

```
%model:`claude-sonnet-4-20250514`
%id:code-reviewer
%wait:planner
Review the code changes and provide feedback.
```

The directives are stripped from the prompt text. The agent will use the specified
model, be named "code-reviewer", and will wait for the "planner" agent to complete
successfully before running.

## Effort Directive

The `%effort` directive (alias `%e`) sets the reasoning-effort level the agent's LLM
provider should run at. `%e:<level>` and `%e(<level>)` behave exactly like the `%effort`
forms, and both resolve to the canonical `effort` directive for duplicate/conflict
validation and prompt cleanup. Bare `%e` (no level) raises the same "requires a level
argument" error as bare `%effort`.

```
%effort:xhigh
%e:xhigh         # same, using alias
%id:reviewer
Audit this module for subtle concurrency bugs.
```

The canonical effort vocabulary is `none`, `minimal`, `low`, `medium`, `high`, `xhigh`,
`max` (ordered least → most). Spelling is validated globally — an unknown level raises a
`DirectiveError`. _Which_ levels a given provider actually honors is decided per
provider; see the [provider support matrix](../providers/models.md#reasoning-effort) in the LLM docs.

You can also attach an effort to a `%model` value with a trailing `@<effort>` suffix
instead of a separate directive:

```
%model:opus@xhigh            # opus, run at xhigh effort
%m:codex/gpt-6.1-sol@high        # alias form, with an explicit provider/model
```

The suffix is split off the clean model before alias/provider resolution, so the
resolved model stays `opus` / `codex/gpt-6.1-sol`. To preserve an `@` that is genuinely
part of a model id, wrap the value in a backtick literal (`` %model:`literal@id` ``) —
backtick literals are never split.

The `@effort` suffix works per branch in a fan-out, so different variants can run at
different efforts (and the effort token is stripped from the generated agent-name
suffixes):

```
%{%m:opus@xhigh | %m:sonnet@low}
Try this two ways and compare.
```

To keep the model fixed and fan out only effort values, put the alt group after
`%effort:`:

```
%m:opus %effort:%{medium | high | xhigh}
Run the same prompt at three effort levels.
```

If both a `%model:...@x` suffix and a separate `%effort:y` survive into the same final
prompt branch with `x != y`, SASE raises a `DirectiveError`; equal values are allowed.

When no `%effort` (or `@effort`) is given, the agent falls back to the
`llm_provider.default_effort` config value, and then to the runtime's own default. An
_explicitly_ requested effort that the chosen provider cannot honor is an error, while a
config-default effort is best-effort (silently skipped with a warning on providers that
don't support it). See [Reasoning Effort](../providers/models.md#reasoning-effort) for the resolution
precedence and per-provider support.

## Hide Directive

The `%hide` directive marks an agent as hidden. Hidden agents are not shown in the
Agents tab by default — press `.` to toggle their visibility. This is useful for
background agents spawned by axe or workflows that don't need active monitoring:

```
%hide
%id:background-checker
Run periodic health checks.
```

## Auto Directive

The `%auto` directive (alias `%a`) requests automatic resolution when the agent reaches
a notification gate. The prompt grammar is closed: `%auto`, `%auto+`, `%auto:true`,
`%auto:plan`, `%auto:tale`, `%auto:epic`, `%auto:manual`, and `%auto:off` are the only
accepted spellings. Any other colon value (backtick literals included, e.g.
`%auto:foo`), any parenthesized form (`%auto(plan=ask)`, `%a(epic=ask)`,
`%auto(plan, epic)`, `%auto()`), and any duplicate `%auto` fail at launch with a
`DirectiveError`. `%auto:manual` and `%auto:off` mean Manual: auto is off exactly as if
no `%auto` were present — the token is still stripped from the cleaned prompt, and
`agent_meta.json` carries a Manual record.

Every launch resolves its `%auto` into one revisioned `agent_meta.autonomy` record, and
one core evaluator decides every automatic gate from that record. A fresh user launch
without `%auto` is **manual**. `standard` is the profile selected by bare `%auto`, not a
global default for every launch:

| Profile    | Prompt selection                           | Tale plan                          | Epic plan                       | Questions                      |
| ---------- | ------------------------------------------ | ---------------------------------- | ------------------------------- | ------------------------------ |
| `manual`   | No `%auto`, `%auto:manual`, or `%auto:off` | Wait for review                    | Wait for review                 | Wait for answers               |
| `standard` | `%auto`, `%auto+`, or `%auto:true`         | Approve, archive, and launch coder | Approve and launch epic workers | Wait for answers |
| `tale`     | `%auto:tale` or `%auto:plan`               | Approve, archive, and launch coder | Wait for review                 | Wait for answers |
| `epic`     | `%auto:epic`                               | Wait for review                    | Approve and launch epic workers | Wait for answers |

These four profiles are built in. `standard` is a profile name for inspection and role
configuration; `%auto:standard` is not accepted by the prompt grammar. No built-in
profile answers questions, including for agents launched before this change once their
runner refreshes, because built-in profile policies refresh from core when read.

Host-composed successors — coders, replanners, pipe/handoff, monitor and gate
follow-ups, and the coder after a manual plan approval — inherit the live record
structurally, and an explicit `%auto` in agent-authored follow-up text can only narrow
it.

Bare `%auto` (`%auto+` and `%auto:true` normalize to it) approves and archives tale
plans — the same path as pressing Enter — approves and launches epic plans, and waits
for human answers to questions. `%auto:plan`, `%auto:tale`, and `%auto:epic`
limit which plan tier auto-resolves: `:plan` and `:tale` cover tale plans only, while
`:epic` covers epic plans only. A plan of the other tier parks for human review instead
of erroring. Questions always wait for you under all three profiles.

```
%auto
%id:auto-fixer
Fix the lint errors in the codebase.
```

sase's TUI and the macro LSP suggest `plan`, `tale`, `epic`, `manual`, and `off` as the
closed `%auto` vocabulary. Launch, sudo, custom, HITL, task/flag triage, snooze,
stale-cleanup, and plugin gates are never auto-resolved and must be answered explicitly.
The `A` toggle in sase's TUI rewrites the agent's record from its next gate: toggling
off makes it Manual, and toggling back on restores its last profile (else `standard`).
Later successors inherit the toggled record.

`sase autonomy explain` predicts each decision exactly — for an agent, a prompt
(`--prompt` dry-runs without executing anything), or a settled gate (`--gate`) —
`sase autonomy log` lists the decisions so far, and `sase autonomy list`/`show` print
the built-in profiles. Generated epic workers take their profile from `autonomy.roles`
(default `standard`), and `sase autonomy list` shows it. Autonomy covers host
checkpoints only; the agent's shell is not restricted. Agents are never told their
profile: SASE adds no autonomy text to an agent's prompt, and the `%auto` token itself
is stripped, so an agent learns only each gate's result.

When an agent launched with `%auto:tale` later submits a tale plan with `/sase_plan` or
`sase plan propose`, sase auto-approves and commits it as an SDD tale in the resolved
plans root's `<YYYYMM>/` directory and launches the coder follow-up — the same path as
the TUI Tale action. An epic plan from the same agent parks for review. Use
`sase repo path plans` to resolve the plans root, which can be in-tree, under
`.sase/sdd/`, or in the split `--plans` sidecar:

```
%auto:tale
%id:cleanup-tale
Tidy up the logging module.
```

## Hold Directive

An **agent hold** is a durable wait in the reverse direction. `%wait` makes a new launch
wait for other work; a hold makes other work wait. While a hold is active, every agent
it matches stays `QUEUED` at the runner-admission gate, even when capacity is free, and
every matching `%proc` unit that has not been dispatched yet stays pending. Work that is
already running is never paused or stopped. Use a hold to quiet the host before
maintenance or a long verification run, or to keep a group of queued agents from
starting until an earlier step finishes.

Holds live in one store (`~/.sase/agent_holds.json`), keyed by the _armer_: the agent or
shell that armed the hold. Each armer has at most one hold. A hold ends when it is
released, when its armer ends (an agent armer's session settles, a `%proc` armer's proc
reaches a terminal state, or a CLI armer's parent shell — or its `hold run` command —
exits), or when its TTL expires. A broken hold store fails open: admission ignores it
rather than stranding a waiter. The [`sase agent hold`](../agents/agent-holds.md#sase-agent-hold) commands
arm, list, show, and release holds, and `sase agent hold run -- COMMAND` holds matching
work only while one command runs. The **Holds** pane in sase's TUI
[Config tab](../tui/admin-center.md#config-tab) lists active holds and releases
one.

The `%hold` directive declares a hold in prompt text, using the same selectors:

```
%hold:planner                                # name selector
%hold:planner,reviewer                       # colon list
%hold:@nightly                               # tribe (positional @)
%hold(pending)                               # freeze WAITING/QUEUED agents in scope
%hold(future)                                # fence launches submitted after the hold
%hold(hood=research)                         # hood selector
%hold(tribe=nightly)                         # tribe selector (keyword form)
%hold(pending, future, ttl=90m, scope=host)  # widest form, explicit in the text
```

| Selector                     | Matches                                                                                                                       |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Name (`planner`)             | An agent, agent session, clan, workflow, or named proc name; role-suffixed names stay exact                                   |
| Tribe (`@nightly`, `tribe=`) | Agents in that tribe                                                                                                          |
| Hood (`hood=research`)       | Agents in that [hood](../agents/index.md), written without a `--role` suffix                                                   |
| `pending`                    | The agents that are WAITING or QUEUED in scope when the hold is armed; later launches and undispatched procs are not captured |
| `future`                     | Agents and undispatched procs submitted after the hold is armed                                                               |

`scope=project` (the default) limits the hold to the armer's project; `scope=host`
covers every project on the machine. `ttl=` accepts durations such as `90s`, `45m`, or
`1h30m` (the `sase agent hold -T` flag takes only single-unit values); without it the
hold uses `agent_hold_default_ttl` (`2h`), and no hold may outlive `agent_hold_max_ttl`
(`12h`). See
[agent hold limits](../config/agents-and-runners.md#agent-hold-limits).

`%hold` may appear more than once; every occurrence is unioned. `hood=` and `tribe=` may
repeat; `ttl=` and `scope=` may each appear at most once per launch unit. Positional
`pending` and `future` are reserved words, `@<tribe>` is a tribe selector, and anything
else is a name. There is no short alias — `%h` remains `%hide`.

`%hold` is always available without a feature flag, and bare `%hold` is a directive
error because a hold needs at least one selector. `%hold` cannot be combined with
`%repeat` or `%dispatch`.

`%hold` is parsed, validated, stripped from the model prompt, carried on typed launch
units, shown in launch previews and confirmation prompts, and armed before launch
admission can dispatch the unit. The launch bundle owns the pre-armed hold until the
agent or proc starts, then rebinds it to that runner. A unit that settles without
dispatch releases its hold. For imperative holds outside a launch prompt, use
`sase agent hold create` or `sase agent hold run`.

A LaunchApproval preview adds a `## Holds` section listing each agent or proc launch
unit that declares a hold, with its canonical directive, scope, and TTL next to the
configured default and cap. A `pending` hold also shows a live count such as
`captures 4 waiting + 2 queued; skips 3 running`. A hold is _broad_ when it combines
`future` with `scope=host`, which would fence every project's later launches, or when
its `pending` capture would freeze more than `agent_hold_confirm_capture_threshold`
(default `10`) agents.

Before submitting a prompt with a broad hold, sase's TUI asks **Arm this hold?** and
uses the current project to count a project-scoped `pending` capture. An interactive
`sase run` also asks for a host-wide `future` hold or an over-threshold host-scoped
`pending` capture. It can count a project-scoped `pending` capture when a typed launch
plan resolves the project, but a plain project-scoped `sase run` prompt without typed
project context skips that count-based confirmation. Declining cancels the launch;
`sase run` prints `Hold not armed; launch cancelled.` and exits `1`. Accepting permits
submission, and the launch path arms the hold. Narrow holds, non-interactive launches,
and launches from inside an agent or proc proceed without the extra confirmation but
still arm their declared holds.

`pending` freezes only agents that already exist; it cannot capture a `%proc` that has
not been dispatched. Use a name selector or `future` to fence procs.

A held agent's `QUEUED` row in sase's TUI ends with `held by <armer>`, and its
`waiting.json` marker and `sase agent list -j` entry carry `held_by` and
`hold_expires_at`. If a held agent and the agent that armed the hold end up waiting on
each other, SASE posts a `Hold deadlock` notification (sender `runner_slot_admission`).
The TTL still guarantees progress, so release the hold or kill one side to resolve it
sooner. Arming and releasing a hold post `agent_hold` notifications. Automatic release
notifications cover both a dead armer and TTL expiry and preserve the arm-time capture
summary and exact expiry boundary. Hold list/show output and the TUI Holds pane show
that stored summary; holds without one display `capture not recorded`.
`sase doctor -C agent_holds.stale` reports holds whose armer died or whose TTL passed.

## Related

- [Directive catalog](directives.md)
- [Directive syntax and completion](directive-syntax.md)
- [Directive composition and fan-out](directive-composition.md)

## `sase autonomy`

Autonomy controls automatic resolution of plan and question gates. A fresh user launch
without `%auto` is manual; bare `%auto` selects `standard`. The `tale` and `epic`
profiles restrict which plan tier resolves automatically. Questions always wait for a
human under every built-in profile. See the
[profile matrix](#auto-directive).

```bash
sase autonomy list
sase autonomy show tale
sase autonomy explain --prompt '%auto:tale'
sase autonomy explain my-agent
sase autonomy explain --gate plan/REQUEST_ID
sase autonomy log my-agent --since 1h --kind plan --outcome auto
```

All four subcommands accept `-j/--json`; bare `sase autonomy` delegates to `list`.
`list` includes effective epic phase/land role assignments. `show PROFILE` accepts
`manual`, `standard`, `tale`, or `epic`. `explain` reads an agent's live record,
dry-runs prompt text with `-p/--prompt` (leaving `$(...)` unexpanded), or reads the
policy revision that decided a settled gate with `-g/--gate`. A gate can be named as
`KIND/REQUEST_ID` or by its gate-turn short ID, member name, or owning agent. `--prompt`
and `--gate` cannot be combined. Prediction does not launch work or answer a gate.

`log [AGENT]` reads host decisions newest first. `-k/--kind` accepts `plan`,
`epic_plan`, or `question`; `-o/--outcome` accepts `auto` or `ask`, and `-s/--since`
accepts a date or relative bound such as `1h`. Manual evaluations leave no log rows.
Launch, sudo, custom, and other privileged gates require human action regardless of
profile. The live TUI `A` toggle applies to the next gate and is inherited by later
successors; see
[Auto-Approve Toggle](../tui/agent-workflows.md#auto-approve-toggle).
