---
title: Bead CLI records
description: Commands for creating, updating, closing, and synchronizing bead records.
---

# Bead CLI records

This page describes commands that create and change bead records.

## `sase bead apply-status <id> <status>`

Set one bead's status through the normal bead-store mutation path. This is the
proc-friendly form of `sase bead update <id> --status <status>`: the full or shorthand
ID routes like any other existing-bead operand, and when the command runs as a durable
proc it writes its typed result to the proc's result sidecar.

See the generated [`sase bead` CLI reference](../cli/bead.md#sase-bead-apply-status) for
this command's options.

## `sase bead attach <id> <file|->...` {#sase-bead-attach-id-file}

Attach snapshots of files to a bead as a new attributed note. The bead keeps the exact
bytes on every machine, even after the file is gone. Use `-` to read one attachment from
stdin (with `-N/--name`).

```bash
sase bead attach <bead-id> ./shot.png
sase bead attach <bead-id> -n "Crash trace" ./trace.json
sase bead attach <bead-id> -N trace.json - < /tmp/trace.json
sase bead attach <bead-id> ./a.png ./b.png
```

The stored note is the prose (when present), a blank line, and the `@attachment:<name>`
tokens.

See the generated [`sase bead` CLI reference](../cli/bead.md#sase-bead-attach) for this
command's options.

## `sase bead attachment list [<id>]` / `open` / `path` / `push`

List content-addressed attachment snapshots, open one in the terminal viewer, or print
the absolute local view path for one attachment. With no child subcommand,
`sase bead attachment` delegates to `sase bead attachment list`. List never fetches;
open and path fetch from the shared store when needed, even above the auto-fetch cap.

```bash
sase bead attachment list <bead-id>
sase bead attachment list <bead-id> --json
sase bead attachment path <bead-id> shot.png
```

`list` text output shows one descriptor per attachment plus the cached view path or an
unavailable marker. `path` materializes the extension-preserving local view and prints
its absolute path, or fails with a clear unavailable error when no shared copy exists.
`open` opens one attachment in the terminal viewer, fetching from the shared store when
needed (with no name, it opens the only available attachment or lists candidates).
`push` drains the upload outbox and promotes local-only objects to the shared stores
without authoring notes.

```bash
sase bead attachment open <bead-id> shot.png
sase bead attachment push
sase bead attachment push <bead-id>
```

See the generated [`sase bead` CLI reference](../cli/bead.md#sase-bead-attachment-list)
for this command's options.

## `sase bead attachment purge <id> <name> -r WHY` / `sase bead attachment prune` {#sase-bead-attachment-purge-id-name--r-why-sase-bead-attachment-prune}

Remove one attachment's bytes everywhere while leaving every bead event untouched
(`purge`), or evict store-confirmed cached objects to fit the local cache budget
(`prune`). `purge` writes a tombstone to each configured shared store, deletes the local
object and its views, and records a local tombstone, so notes keep their text and render
`(purged)` while fetches refuse the digest. It previews every note that references the
digest, confirms on a TTY (or `-y/--yes`), and prints the manual `git filter-repo`
history-erasure procedure, which is never automated. `prune` prints a dry-run plan by
default and evicts with `-y/--yes`; pending-upload and local-only objects are never
evicted. `sase bead doctor` reports token/manifest mismatches, dangling descriptors,
pending uploads, local-only objects, tombstoned references, digest mismatches, and
orphans older than 7 days; `sase bead doctor --fix-attachments` removes orphans,
re-drains the outbox, and quarantines corrupt objects.

```bash
sase bead attachment purge <bead-id> shot.png -r 'contains a secret' -y
sase bead attachment prune
sase bead attachment prune -y
sase bead doctor --fix-attachments
```

## `sase bead +1 <task-id>`

Corroborate an existing task with independently attributed evidence. `--note` is
required; a value of `@<path>` is read from that file. `--ref` is repeatable and
`--author` overrides normal current-agent attribution. Each reporter counts once, the
creator does not count, and repeat reporters are unchanged no-ops. New evidence promotes
`open` tasks to `ready` atomically. Closed tasks promote only when the report's
`observed_since` window starts strictly after the current close, archiving close
metadata into close history and clearing the assignee; missing provenance preserves the
default reopen behavior. Stale post-close evidence is recorded with `observed_since`,
shown with the post-close evidence marker and `+1 after close` badge, and leaves the
close standing. `--verified-after-close` asserts that the defect was reproduced on a
tree already containing the close and uses the current instant as the observation-window
start. Other active statuses are preserved, and plan or phase beads are rejected. See
[Task Corroboration (+1)](bead-triage.md#task-corroboration-1) and
[Close History](bead-triage.md#close-history).

## `sase bead close <id> [<id2> ...]`

Close one or more issues. (A worker's final `sase stitch create -B close` commit or PR
also closes its assigned in-progress bead — see
[Standalone Task Workflow](bead-triage.md#standalone-task-workflow) — so an explicit
close is usually only needed for canceling, superseding, or a non-commit resolution.)
Every requested bead is checked before the first write, so a batch either closes
completely or leaves the store untouched. Inside a SASE agent run, a target that differs
from the assigned bead by one interior segment is refused: the command names both IDs,
exits non-zero, and writes nothing. A bead with any non-closed descendant is rejected
and names the unfinished work; phase agents should continue to close only their assigned
phase bead, not the parent epic. Closing does not touch a bead's existing
[close history](bead-triage.md#close-history); a new record is only archived there the
next time the bead reopens.

Closing a bead that is already closed exits successfully and reports `Already closed`
without appending another close event, changing `issues.jsonl`, or creating a store
commit. If the repeat close includes a note, the note is still appended and committed as
a note-only mutation. If the repeat close supplies an explicit `--resolution` or
`--reason` that disagrees with the recorded close, the command exits non-zero before
writing and points at `sase bead open` or `sase bead note` as the appropriate remedy.

For an epic plan bead, `--phases` (`-p`) closes phase beads by their numeric bead-ID
suffix: for example, `sase bead close <epic-id> -p 1-3,5` closes `<epic-id>.1`,
`<epic-id>.2`, `<epic-id>.3`, and `<epic-id>.5`. The epic target itself may be full or
shorthand. The option accepts comma-separated numbers and inclusive ranges, may be
repeated, and requires exactly one epic ID. It never closes the epic itself. A
plan-tier, untiered, or phase target is rejected without writing to the store.

`--force` is the explicit exception for canceling or superseding an unfinished tree. It
requires a non-empty reason and an explicit `canceled` or `superseded` resolution;
`--force --resolution done` is rejected. A forced close recursively closes the
unfinished descendants with the same non-done resolution, gives each one a close reason
naming the forcing parent, and records the swept descendant IDs in that parent's close
event.

`--note` appends one attributed note to every explicitly listed bead before any close
events, in the same mutation, so completion evidence and the close land in one commit
and one push instead of two. The note entry is stored as a `note_appended` event,
matching `sase bead note`; forced closes apply it only to the listed beads, never to the
swept descendants. Keep `sase bead note` for mid-work progress notes and for adding
evidence to a bead that is already closed.

Closing a plan or phase bead that still has Justfile `--epic-symbol` entries keyed to it
(or to a descendant suffix) is rejected before any store write. The error lists the
exact flags. They go stale the instant the bead closes and turn unrelated agents'
`just check` red, so resolve each symbol or re-key the line to a still-open bead first.
List the entries with `sase bead epic-symbols <id>`. Already-closed no-ops skip this
check. `--force` does not bypass it: leftover entries still break the lint gate.

Closing a `flag` task bead is rejected the same way while the working tree's
`src/sase/feature_flags/registry.py` still defines a flag naming it
(`check_feature_flags` rule 7 would turn every workspace red). The registry is parsed
statically, not imported, and the error names each surviving flag key. In the same
change, delete the flag's Off branch, make its On branch unconditional, and remove the
registry entry, or keep the bead open. A tree with no registry file skips the check. The
flag-triage gate's deliberate Close action is unaffected.

Closing a delegated child plan/epic also closes its parent phase automatically once
every child of that phase is closed. This upward cascade continues only through phase
parents and never auto-closes a parent plan/epic; the parent land agent retains that
responsibility. Removing a child epic does not trigger the cascade, so its phase stays
open and can be scheduled again on retry.

When a close changes the store, SASE commits it and then publishes it according to
`sdd.push_after_commit` (default: `async`), followed by the
[publication check](bead-storage.md#publication-verification) that turns an unpublished
mutation into a failure instead of a false success. Use `--no-push` to keep the commit
local while batching bead mutations, then publish the batch with a later
`sase bead sync`.

See the generated [`sase bead` CLI reference](../cli/bead.md#sase-bead-close) for this
command's options.

## `sase bead create`

Create a new issue. Every create requires `-w/--reason`; see
[Creation Reason](beads.md#creation-reason).

See the generated [`sase bead` CLI reference](../cli/bead.md#sase-bead-create) for this
command's options.

Patch metadata is valid only on plan beads. It is used by the epic-approval and
`sase bead work` flows to keep plan beads linked to the Patch they are intended to
produce.

New beads are attributed to the acting SASE agent (from `SASE_AGENT_NAME` or
`agent_meta.json`), falling back to the store owner when no agent identity resolves. A
`phase` bead always inherits its creator from its parent epic instead of being
attributed independently. A `plan` bead prefers the `proposed_by` value
`sase plan propose` stamps onto the plan file at proposal time, and falls back to the
acting agent when the plan carries none. See
[`sase bead show`](bead-cli-inspection.md#sase-bead-show-id-id2) for how the resolved
creator is displayed.

## `sase bead dep`

Inspect and manage dependency edges. With no child subcommand, `sase bead dep` delegates
to `sase bead dep list` and prints the same central delegation notice used by other
default-list verbs.

```bash
sase bead dep
sase bead dep add <issue> <depends_on>
sase bead dep list [<id>]
sase bead dep rm <issue> <depends_on> [<depends_on2> ...]
sase bead dep tree [<id>]
sase bead dep add 001.2 001.1
```

`dep add` makes `<issue>` depend on `<depends_on>`. The issue becomes blocked if the
dependency is not yet closed.

`dep list` prints dependency edges with their blocking state and recorded provenance. A
scoped read, such as `sase bead dep list beads-001.2`, includes every bead status by
default because closed dependencies are usually what you need to see when explaining
readiness. A store-wide read defaults to `open`, `claimed`, `ready`, `snoozed`, and
`in_progress`, matching `sase bead list`. The `-s/--status` filter currently accepts
only `open`, `claimed`, `in_progress`, and `closed`. The current `dep list --help` and
`dep tree --help` descriptions still omit `ready` and `snoozed` from their stated
store-wide defaults; the five-status list here reflects the runtime behavior.

`dep tree` walks the dependency graph as a deterministic tree. `--direction out` follows
what the root waits on, `--direction in` follows what is waiting on the root, and
`--direction both` renders both trees. Store-wide trees use the same active-status
default as store-wide `dep list`; scoped trees include every status by default.

Tree output marks graph states explicitly:

- `⇡ (shown above)` means a shared subtree was already expanded, as in a fan-in diamond.
- `↻ (cycle)` means a dependency cycle was detected and that branch stopped.
- `(+N more, use --levels 0)` means `--levels` truncated descendants.
- `? <id> (not found)` means an edge points at an unresolved bead ID.

`dep rm` removes one or more existing dependency edges from `<issue>` in one
all-or-nothing mutation. The command records `dependency_removed` events and then
reports whether the source bead is ready or still blocked.

See the generated [`sase bead` CLI reference](../cli/bead.md#sase-bead-dep) for this
command's options.

## `sase bead ref`

Inspect and manage artifact references attached to beads. With no child subcommand,
`sase bead ref` delegates to `sase bead ref list`.

```bash
sase bead ref add <id> <ref> [<ref2> ...]
sase bead ref list [<id>]
sase bead ref list <id> --resolve
sase bead ref rm <id> <ref> [<ref2> ...]
```

`ref add` normalizes every supplied reference, appends entries that are not already
present, and reports a no-op when the bead already carries all of them. `ref rm` removes
the supplied normalized references and leaves absent entries alone. Both commands record
per-reference events, so concurrent agents attaching different references do not replace
each other's entries.

`ref list` prints stored canonical references. With `--resolve`, it also reports where
each reference resolves from the current workspace (or, for a bead routed to another
enabled project, from that project's primary workspace), or that it resolves nowhere.
The optional bead ID scopes the listing to one bead; without it, the command lists beads
in the current store that carry references. Add `--json` for a stable machine-readable
response.

See the generated [`sase bead` CLI reference](../cli/bead.md#sase-bead-ref) for this
command's options.

## `sase bead init`

Initialize the bead store for the current project. In effective in-tree SDD mode this is
`sdd/beads/`; local and separate-repo modes use `.sase/sdd/beads/`. Split sidecar mode
uses the root of the `--beads` repository once the store record names that sidecar, and
`beads/` in the `--plans` repository until then.

A newly initialized store's default `issue_prefix` is the project's `PROJECT_NAME`
display name (falling back to the internal ProjectSpec key, then the git remote's repo
name, then the directory name) rather than the raw ProjectSpec key. Stores created
before this change that already leaked the key are forward-repaired automatically before
their next top-level bead is minted. Use `sase bead doctor --fix-issue-prefix` to repair
one on demand before creating another bead (see
[`sase bead doctor`](bead-cli-query.md#sase-bead-doctor)).

## `sase bead onboard`

Display a quick-start guide with common command examples, including required task size,
`/sase_new_task` agent policy, and task corroboration.

## `sase bead open <id>`

Reopen an issue with an `issue_opened` event. Every closed ancestor above it is reopened
in the same mutation, and the command prints the ancestor IDs it changed. Inside a SASE
agent run, a target that differs from the assigned bead by one interior segment is
refused the same way as [`sase bead close`](#sase-bead-close-id-id2): both IDs are
named, the command exits non-zero, and nothing is written. Resolutions, close reasons,
and close timestamps are archived into each reopened bead's close history instead of
being discarded — see [Close History](bead-triage.md#close-history); the full history
also remains available in `sase bead history --format full`.

## `sase bead resolve-conflicts`

Resolve merge or rebase conflicts in generated bead state from the current store. Only
`events/manifest.json`, `config.json` (when only `next_counter` conflicts), and
`events/streams/*.jsonl` conflicts are merged automatically; any other conflict is left
for you. See [Duplicate Bead IDs](bead-storage.md#duplicate-bead-ids) for how add/add
stream conflicts are relocated.

## `sase bead rm <id> [<id2> ...]`

Remove one or more issues and recursively cascade-delete the union of all their
descendants, including phases nested beneath child epics. Every requested ID is
validated before anything is removed, so a missing ID leaves the store unchanged.
Overlapping or repeated selections remove and print each issue only once. This is
irreversible.

## `sase bead snooze <id> [<id2> ...]`

Defer one or more `open` or `ready` task beads. See
[Snoozing a Task Bead](bead-triage.md#snoozing-a-task-bead) for the full workflow.
Multiple IDs apply the same wake time, `+1` target, and reason atomically, matching
`sase bead update`'s batch semantics.

See the generated [`sase bead` CLI reference](../cli/bead.md#sase-bead-snooze) for this
command's options.

## `sase bead sync`

Regenerate the compatibility projection from the canonical event store and stage bead
state in git. It does not create a commit; the staged event/projection files are
included in the next normal project or SDD commit.

See the generated [`sase bead` CLI reference](../cli/bead.md#sase-bead-sync) for this
command's options.

## `sase bead sync-external`

Run one external tracker mirror pass — the same reconciliation path the
`external_issue_mirror` AXE job runs every fifteen minutes. See
[External Issue Mirroring](bead-mirroring.md#external-issue-mirroring).

See the generated [`sase bead` CLI reference](../cli/bead.md#sase-bead-sync-external)
for this command's options.

## `sase bead update <id> [<id2> ...]`

Update one or more fields on one or more issues. Every listed bead receives the same
field changes in a single all-or-nothing store mutation: every ID is resolved and every
resulting issue is validated before anything is written, so an unknown ID or an invalid
field value leaves every named bead untouched. Inside a SASE agent run, a target that
differs from the assigned bead by one interior segment prints the near-miss warning on
stderr and still applies the update. Duplicate IDs, including a shorthand alongside its
resolved full form, collapse to a single update. A single-ID invocation is unaffected —
same syntax, output line, and commit message as before.

See the generated [`sase bead` CLI reference](../cli/bead.md#sase-bead-update) for this
command's options.

`task_type` is immutable: `sase bead update` has no `--task-type`. An attempt is
rejected with a message pointing at close-and-recreate. The filing reason is immutable
the same way: update has no flag for it. See
[Creation Reason](beads.md#creation-reason).

`sase bead update --notes` is rejected because it can replace the whole note field and
delete earlier notes. Notes are append-only, and `--note` appends the same attributed
record to every named bead inside the same mutation — a batch form of `sase bead note`.
`--notes` still parses (hidden from `--help`) so passing it exits non-zero with a
message pointing at `sase bead note` (single bead) or `sase bead update --note` (batch)
instead of failing as an unrecognized argument. Use `sase bead note --edit`/`--remove`
to correct or retract an individual record.

Beads whose requested fields already hold the requested values are quiet no-ops: they
are reported as `Unchanged`, excluded from the commit, and an all-no-op batch writes
nothing. `--status closed` keeps the descendant guard that prefers `sase bead close`,
evaluated against the whole batch: a descendant that is itself being closed by the same
invocation counts as closed, so argument order does not matter, but a descendant left
out of the batch still rejects the whole update.

## Related

- [Bead CLI](bead-cli.md)
- [Bead triage](bead-triage.md)
