---
title: Starting bead work
description: How `sase bead work` resolves plans and starts assigned bead work.
---

# Starting bead work

This page describes how `sase bead work` starts plan, epic, and task work.

## `sase bead work <target> [<target> ...]` {#sase-bead-work-target}

Create or resume one or more epics from validated Markdown plans, launch existing
epic-tier plan beads, launch standalone task beads, or run an ordered mix of those
targets. Each target is treated as a plan file when it ends in `.md`, contains a path
separator, or names an existing file; other targets are bead IDs whose type selects the
epic or task path. Epic modes run one agent per non-closed, non-delegated phase plus a
final land agent; a retry with authored phases that are all already closed launches only
the land agent. Task mode runs exactly one deterministic worker; see
[Standalone Task Workflow](bead-triage.md#standalone-task-workflow) for its full
lifecycle.

Multiple targets use shell-`&&` style sequencing: SASE finishes each target before
starting the next, stops at the first error, and does not validate or launch later
targets after that error. Successful earlier targets keep their output and side effects;
there is no batch rollback. A declined launch confirmation still counts the same way it
does for a one-target command: the current target returns success after printing
`Aborted.`, so the next target may run.

Flags are command-wide and are applied independently to every processed target.
Target-local validation is unchanged, so plan-only flags such as `--parent`,
`--artifacts-dir`, and `--cl-name` work for earlier plan files and then stop the
sequence if a later bead-ID target reaches the same incompatible flag. `--json` prints
one complete result object per processed target. A one-target JSON run is unchanged; a
multi-target JSON run is newline-delimited JSON, one object per line, including the
first failing target's error object when the command stops.

`-c/--capacity N` is an epic-only invocation control: every selected phase and land
segment emits `%queue(capacity=N)`, except that a segment whose macro claims more weight
gets a budget equal to that weight (`ceil(weight)`). `N` is that launch's own admission
budget and must be at least 1; `1` means run alone. Omission preserves default queue
behavior. The option applies to epic bead IDs and epic Markdown plan targets. An
explicit capacity on a standalone task target is an actionable error: earlier successful
targets stand and processing stops. When a segment is raised above `N`, the work-plan
summary prints `Capacity: requested N · <agent> raised to M (queue weight W)`. The raise
always applies: every segment gets `max(N, ceil(authored_weight))`. Before it marks the
epic ready, preclaims beads, or spawns anything, SASE expands each phase and land macro
to check the combined queue fields: a macro that sets its own `%queue(capacity=...)`
conflicts with `--capacity`, and that target fails (under `--dry-run` too) without
changing any bead or agent state. `-C/--cl-name NAME` retains the existing
completion-notification behavior and plan-file restriction.

`-w/--wait SPEC` holds launched epic phases until every named dependency finishes.
`SPEC` is a comma-separated list of agent names and `bead=<id>` entries; `time=`,
`runners=`, `priority=`, `unit=`, and `proc=` are rejected. A parse error exits 2 before
any bead or file mutation. The option applies to plan-file targets and existing epic
beads. Extra waits are appended only to segments whose intra-epic `waits_on` is empty —
the current root wave, and the land segment when it does not wait on phases — after
those segments' existing wait lines and before their `#<macro>` line. Dependent segments
inherit the wait transitively and do not repeat it. A `bead=<id>` entry may name a full
ID from another enabled project; the waiting segment stays parked until that bead's
owning store shows it closed, including while the ID is ambiguous or its store is
unavailable. Shorthand `bead=` entries keep the launching project's scope.

A full epic or task bead ID from another enabled project launches in that project's
context: SASE reads and checkpoints the owner's bead store, resolves the owner project's
bead-work macros, and prefixes each segment with the owner's VCS workflow and project
name. `--dry-run` reads the owner's store without materializing it. In plan-file mode, a
`parent_bead` or `--parent` that belongs to another enabled project archives the plan
into that project's SDD store and creates the epic in its bead store. A machine-local
plan's frontmatter `project` field routes plan-file mode to that project's primary
checkout when the working directory is outside it (no project, `home`, or a different
project). The command then uses that project's lock, stores, archive links, and launch
context, as if it had been run from the primary checkout. A working directory already
inside that project (primary checkout, numbered workspace, or host-leased checkout)
keeps local store resolution. An unknown or ambiguous `project` value fails before any
mutation. When routing, a parent bead that belongs to a different project than the
frontmatter is refused; use `--parent top-level` to create an unparented epic. Plans
without the field keep working-directory and parent-bead routing as before.

For a task bead, `sase bead work <task-id>` accepts `ready` (normal), `open` (manual
launch), or recoverable `in_progress` state. It does not launch a duplicate when the
assigned agent is still alive, and it rejects closed tasks. `--dry-run` prints the
single worker prompt without changing the bead or agent registry. A real launch:

1. Force-reuses the task ID as the deterministic agent name after showing or confirming
   any destructive cleanup.
2. Selects the bead's stored model or its size-derived phase-worker alias; missing
   missing size defaults to small.
3. Renders one VCS-aware prompt ending in `#bd/work_task:<task-id>`, plus `#plan` for
   large/xlarge tasks.
4. Sets `status=in_progress` and `assignee=<task-id>` in one checkpoint commit,
   publishes it, then launches the worker.
5. Restores the prior task state if dispatch fails before any runner starts; a live
   runner keeps the checkpoint.

A launch that can only run on a **hard**-disabled provider is refused with a
provider-and-expiry diagnostic before any runner starts — the same fail-closed guard
`sase run` and sase's TUI use. A **soft** disable does not refuse the launch. See
[Provider routing](../tui/launch-control.md#provider-routing-controls).

The `TaskTriage` gate's default Launch branch submits this command as an unattributed
proc with `--yes-to-all`; optional gate feedback is appended to the worker prompt.

Plan-file mode is the canonical epic-approval entry point. It:

1. Validates the file against the epic plan schema and reports the complete diagnostics
   on failure.
2. Resolves the project's SDD and bead stores, initializing the bead store when needed.
3. Archives the plan under the resolved `{YYYYMM}/` plans directory and commits it.
4. Resumes the linked epic when the archived plan already has a valid `bead_id`.
5. Otherwise creates the epic plan bead from the plan's `title`, `goal`, top-level
   `model`, optional `parent_bead`, and optional Patch metadata; creates phase beads
   with their authored sizes in `phases[]` order; wires every `depends_on` edge; and
   commits the new `bead_id` link.
6. Invokes the existing bead-ID launch path.

A missing phase description becomes a deterministic pointer to the plan and phase ID. A
linked `bead_id` that is missing fails with instructions to remove the stale link or
restore the bead store. Failures before the launch checkpoint is committed remove the
newly-created epic and children and restore the plan link. A publication failure after
the checkpoint preserves the linked, preassigned epic as the safe retry point even
though no runner spawned. If dispatch fails with no runner spawned, plan-file mode
removes a newly created graph and restores the plan link; for an epic that already
existed, it instead restores that epic's prior readiness, assignments, and statuses.
Once a runner has spawned, the linked epic and checkpoint are preserved for recovery and
partial runners are terminated. Every plan-file failure after archiving prints the exact
`sase bead work ... --yes` command to resume.

When an epic-tier plan is proposed from bead work, `sase plan propose` automatically
stamps `parent_bead` from the phase agent's `SASE_PHASE_BEAD_ID`, from the land agent's
`SASE_EPIC_BEAD_ID`, or from the task worker's `SASE_BEAD_ID`. Plan-file mode resolves
that bead and creates the new epic beneath it, yielding recursive IDs such as
`beads-001.2.1` or `<parent-bead-id>.1`; an unresolved parent fails with a remedy
instead of silently creating a top-level epic. A task bead that spawned a child epic
cannot be closed until that child epic closes. `--parent <bead-id>` overrides the
authored association, while `--parent top-level` explicitly creates an unparented epic.
The override applies only to plan-file targets.

`--dry-run` plan-file mode validates and resolves the stores, previews the archive
destination, parented epic ID, authored beads, routed models, and dependency waves, and
does not write files, create beads, reserve names, or launch agents. `--json` prints one
stable object for scripting; successful human output always ends with a grep-friendly
`Epic: <id>` line used by approval hosts.

Once an epic bead exists, the shared launch path:

1. Validates that `<epic_id>` resolves to an issue of type `plan` with `tier=epic`. If
   the plan is already marked `is_ready_to_work`, the command treats the run as a retry
   and schedules any remaining non-closed phases. If the epic has authored phase
   children but every one is already closed, the retry schedules zero phase agents and
   still launches or recovers `<epic_id>.land`; an epic with no authored phase children
   remains invalid. A phase that owns a non-closed child plan/epic is delegated work
   already in flight and is skipped until that child closes or is removed; retries
   therefore do not launch a duplicate phase agent.
2. On a confirmed launch, force-reuses the deterministic bead-work names —
   `<epic_id>.<N>` (for each open phase), `<epic_id>.land` (for the land agent), and the
   additional `<epic_id>` land-agent name. It wipes any prior owner of those names that
   is a completed, failed, dismissed, or planned reservation, or a live worker still
   waiting to start (waiting owners are stopped). A live owner that is already running
   is preserved: its slot is not relaunched. This also covers owners that hold the name
   only as a `workflow_name`. If the forced-reuse cleanup cannot complete (a wipe fails
   or a name is still reserved afterward), the command aborts before mutating any bead
   state. A waiting phase, land, or task worker is not considered reusable merely
   because a signal was sent: SASE records explicit kill intent, waits for the old
   process group to stop, escalates when needed, and only then removes artifacts,
   releases workspaces, preclaims beads, or launches the replacement. If two waiting
   turns share the same selected name, every matching turn must be confirmed stopped
   before the new turn can reuse that name; an unresolved or still-running duplicate
   blocks the launch. `--dry-run` performs no cleanup; it only warns which live agents a
   real launch would force-reuse.

   The itemized preview labels each existing agent with the action cleanup would take —
   `BLOCKED`, `PRESERVE`, `KILL`, `REMOVE`, or `RELEASE`. Rows are grouped in that
   order, then sorted by agent name, and each prints as
   `ACTION (current-state) agent-name bead=<expected-bead> reason`, with the `bead=`
   part omitted when the slot has no expected bead. `BLOCKED` marks a slot whose
   existing owner cannot be safely classified, usually a conflicting bead association,
   an unknown live state, or a second still-running turn that holds the same name;
   session and clan members reached without their own bead ids are accepted rather than
   treated as conflicts. Every blocker is listed instead of aborting on the first one,
   and a real launch still stops before any wipe, bead mutation, or spawn. `--dry-run`
   renders the `BLOCKED` rows, reports how many blockers would abort a real launch, and
   still exits `0`.

3. Flips the epic plan bead's `is_ready_to_work` flag to `True` when it was not already
   ready.
4. Builds a Kahn-wave schedule from the epic's schedulable open phase children,
   respecting dependencies and excluding delegated phases with an open child plan/epic.
   When every remaining phase is delegated, or when no non-closed phase remains on a
   retry, only the land agent is launched and remains parked behind the phase beads that
   have not closed yet.
5. Associates each rendered worker with exactly one bead in its `%id`: the first phase
   uses its full agent name plus `bead=<phase-id>` beside the separate clan declaration,
   later phases combine their suffix, `clan=<epic-id>`, and `bead=<phase-id>`, and the
   land agent combines `land`, the clan, and `bead=<epic-id>`.
6. Renders a single `---`-separated multi-prompt. Each per-phase agent is named
   `<epic_id>.<N>` and references the
   [`work_phase_bead`](../macros/tags.md#available-tags) macro; a final land agent named
   `<epic_id>.land` references the [`land_epic`](../macros/tags.md#available-tags)
   macro. Every segment joins clan `<epic_id>` and assigns that whole clan to tribe
   `@epic` with the single `%clan(<epic_id>, tribe=epic)` directive. Each phase
   dependency becomes both a `%w(<blocker-agent>, for_epic=false)` wait on the blocker
   phase-agent name and a `%w(bead=<blocker-phase-id>)` closure wait. The explicit
   `for_epic=false` keeps intra-epic sequencing agent-only under the flipped follow
   default. The land agent likewise waits on every launched phase agent and on every
   authored phase bead, including already-closed or currently delegated phases.
   Requiring both conditions prevents a phase that delegated to a child epic from
   releasing dependents merely because its original agent finished; the child epic must
   land and close the parent phase first. A failed or killed phase keeps dependents and
   the land agent parked until its agent name is retried successfully and its bead
   closes. `xsmall`, `small`, and `medium` phases implement directly with
   `%model:@xsmall`, `%model:@small`, and `%model:@medium`, respectively. Only `large`
   and `xlarge` phases append `#plan` after their work reference and use `%model:@large`
   and `%model:@xlarge`. Each size alias resolves directly to its configured target —
   there is no intermediate hop through a second alias. A stored phase `model` always
   wins over the size-derived alias without changing whether the phase receives `#plan`,
   and a missing size behaves as `small`. The land agent emits `%model:<value>` when the
   epic plan bead has a stored `model`. Without one, it emits the configured
   `llm_provider.epic_lander_model` (shipped default `@large`) below
   `bead.big_epic_phase_threshold` and the configured
   `llm_provider.big_epic_lander_model` (shipped default `@xlarge`) at or above the
   threshold (default `5`), using the total authored phase count even when resumed work
   has already-closed phases. These two fields are independent, directly-configured
   scalars with their own shipped defaults; neither chains through the other or through
   any other alias. Builtin size aliases can be configured under
   `llm_provider.model_aliases.builtin`. Every phase and land segment carries the
   `%auto` line for its `autonomy.roles` profile (see
   [configuration.md#autonomy](../config/agents-and-runners.md#autonomy)). The default
   is `standard`: submitted tale plans are approved and archived, and submitted epic
   plans are approved and launched as child epics beneath the phase or land bead.
   Setting the role to `tale` makes nested epic plans park for human review. An agent
   may author a tale or an epic as needed; the plan's authored `tier` selects the
   corresponding follow-up path. The land agent prefers a tale for remaining work that
   one agent can finish. Because nothing resumes the landing after a tale's coder
   finishes, the land agent triages follow-ups first and writes the epic's closeout into
   the tale as its final step, while a child epic instead hands the resumed landing to
   its own land agent through `parent_bead`.
7. Before spawning any runner, batch-preassigns every scheduled phase bead to its
   rendered worker and the epic bead to `<epic_id>.land`, setting all of them to
   `in_progress`. It commits readiness, assignments, and the complete graph as one
   `chore(beads): checkpoint approved epic graph <id>` checkpoint. A retry whose graph
   is already committed may have no new checkpoint commit. Before dispatch, SASE applies
   the target-specific synchronization rules below.
8. Dispatches the rendered multi-prompt. Runner-side waiting claims and launch
   promotions see their preassignment and become no-ops. Each segment uses a force-reuse
   `%id(!<agent_name>, bead=<bead-id>)` form (with `clan=` on join segments), so
   re-running `sase bead work` after a killed or failed run wipes stale name owners
   before relaunch. The schedule is status-blind and uses agent liveness, which makes
   the checkpoint safe to retry.

When a phase agent authors an epic-tier implementation plan, every phase and land
segment carries the `%auto` line for its `autonomy.roles` profile (see
[configuration.md#autonomy](../config/agents-and-runners.md#autonomy)). The default is
`standard`: submitted tale plans are approved and archived, and submitted epic plans are
approved and launched as child epics beneath the phase or land bead. Setting the role to
`tale` makes nested epic plans park for human review. Once approved, the child epic is
created beneath the phase and the phase remains open while delegated work runs. A
planner whose phase already holds an earlier agent's unfinished increment authors a
child epic whose phases each fit one coding agent instead of another single-agent tale.
Landing the child epic triggers the upward close cascade described above, which closes
the phase and lets its bead-gated dependents proceed. Until then, parent-epic retries
skip that delegated phase. The land agent now genuinely requires every phase bead to
close; if a phase crashes before closure, retry or close that phase explicitly rather
than expecting landing to sweep it up.

See the generated [`sase bead` CLI reference](../cli/bead.md#sase-bead-work) for this
command's options.

Progress, timing, and admission are separate from the dependency schedule. Kahn waves
and `%w` waits decide _order_; they do not wait for an LLM or a runner slot merely to
register the remaining deterministic names. Capacity admission is when a spawned child
actually acquires a runner. A fast CLI return means the requested names are reserved and
the children are registered, not that every child has already been admitted to a
provider. `already_running` retries return before cleanup, bead writes, publication, or
reservations.

Human stderr may print throttled `launch_timing target=... stage=...` lines while a
launch is in progress (current target/stage and completed/total owners when known).
Those lines are progress, not part of the command's JSON contract: `--json` still prints
one complete result object per processed target (newline-delimited for several targets)
and is otherwise byte-stable. Enable the same structured stage records at info level
with `SASE_BEAD_WORK_TIMING=1` (bead work) or `SASE_AGENT_LAUNCH_TIMING=1` (generic
agent launches). Durable stage and summary events also append to
`~/.sase/logs/tui_launch_timing.jsonl` (overridable with `SASE_TUI_LAUNCH_TIMING_PATH`).
`--dry-run` does not create reservations or mutate agent/bead state.

The work macros are resolved by `MacroTag` (tag-based lookup), so a project-local or
user-defined `work_phase_bead`, `work_task_bead`, or `land_epic` macro overrides the
built-in. For epic-tier work, every phase and land segment carries the `%auto` line for
its `autonomy.roles` profile (see
[configuration.md#autonomy](../config/agents-and-runners.md#autonomy)). The default is
`standard`: submitted tale plans are approved and archived, and submitted epic plans are
approved and launched as child epics beneath the phase or land bead. Setting the role to
`tale` makes nested epic plans park for human review, without a human-in-the-loop
checkpoint between dependency waves.

When the epic plan bead is attached to Patch metadata (`--patch`, `--changespec`, or
`--bug-id`), `sase bead work` preserves the current project's VCS context in the
generated prompt. The first phase segment targets the project reference and adds a `#pr`
reference for the Patch, while later phase and land segments target the Patch ref
directly. For non-Patch epics launched from a known SASE workspace, each segment is
still prefixed with the project's
[project tag](../macros/reference-syntax.md#project-tags) (for example `+sase`, which
expands to `#gh:gh_sase-org__sase`); a bead routed to another enabled project uses that
project's tag. If the current directory is not associated with a SASE project, the
prompts are left unprefixed and run in the caller's normal launch context.

If checkpoint creation fails before it commits, the command restores every phase/epic
status and assignee it changed, and restores `is_ready_to_work` only when this attempt
set it. A detached-store publication failure after the local checkpoint commit stops
before spawning and preserves that checkpoint as the safe retry point; rerun without
`--no-push` after fixing the remote. For an existing epic, an agent-dispatch failure
before any runner spawns restores the prior assignments and commits the recovery.
Plan-file mode additionally removes a graph created by that invocation and restores its
plan link. A partial-spawn failure SIGTERMs the children it did start and preserves the
preassigned checkpoint for recovery. An epic that was already ready remains ready.

Successful launches do not add a post-launch bead commit: the pre-spawn graph checkpoint
is the complete launch-owned state. The accepted `bead.push_after_commit` configuration
field is not consulted by this current path. The exact synchronization sequence depends
on the target:

- For a bead-ID target, SASE runs the managed sync worker synchronously after the
  checkpoint unless `--no-push` was passed. A store with no Git remote makes that sync a
  local no-op. Any reported sync or push error stops the launch before dispatch,
  including for an in-tree Git store. A remote-backed detached store has the additional
  requirement that the checkpoint was actually pushed.
- For a plan-file target, SASE synchronously publishes a remote-backed detached bead
  graph before dispatch. After a successful dispatch it makes a best-effort synchronous
  push of the plans store, which publishes the archived plan and its `bead_id` link. A
  failure in this later plans-store push is a warning, not a launch failure.
- `--no-push` skips these synchronization steps. It is usable only when workers can see
  the local checkpoint directly; a remote-backed detached bead store exits nonzero
  before any agent is spawned.

## Related

- [Bead CLI](bead-cli.md)
- [Bead TUI integration](bead-tui.md)
- [Plans](plans.md)
