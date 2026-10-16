---
title: Beads
description: Bead identities, types, and the data model used to track work in SASE.
---

# Beads

Beads are git-portable records that track work and dependencies across SASE projects.

Bead is a lightweight, git-native issue tracking system built into sase. It uses
Rust-backed event storage, query/reduction, and mutation logic through the required
`sase_core_rs` extension, with generated JSONL compatibility projections for older
tooling (inspired by [Fossil](https://fossil-scm.org/)). Issues are organized into
plan-like containers, executable child phases, and standalone task beads for discovered
follow-up work. Plan beads can represent ordinary plans or executable epics through
their `tier` metadata; task beads capture independent work that does not need an epic
DAG.

Bead is a lightweight, git-native issue tracking system built into sase. It uses
Rust-backed event storage, query/reduction, and mutation logic through the required
`sase_core_rs` extension, with generated JSONL compatibility projections for older
tooling (inspired by [Fossil](https://fossil-scm.org/)). Issues are organized into
plan-like containers, executable child phases, and standalone task beads for discovered
follow-up work. Plan beads can represent ordinary plans or executable epics through
their `tier` metadata; task beads capture independent work that does not need an epic
DAG.

## Quick Start

```bash
PLANS_ROOT=$(sase repo path plans)
sase bead init                                          # Initialize beads in current project
sase bead create -t "New feature" --type "plan(${PLANS_ROOT}/202605/feature.md)" --tier plan \
  -w "Track the feature plan before implementation starts"
sase bead create -t "Epic" --type "plan(${PLANS_ROOT}/202605/epic.md)" --tier epic \
  -w "Break the feature into phased work"
sase bead create -t "Sub-task" --type "phase(beads-001)" --size small \
  -w "The epic plan calls for this phase" # Create a sized epic phase
sase bead create -t "Fix flaky test" --type 'task(flake)' --size small \
  -w "CI flakes on the retry path" \
  -f node_id=tests/foo.py::test_bar -f evidence='failed then passed' # Create a typed draft task
sase bead +1 beads-002 --note "Independent reproduction" # Corroborate an existing task
sase bead update beads-002 --status=ready               # Offer the task for human triage
sase bead list                                          # List open, claimed, ready, snoozed, and in-progress issues
sase bead list --status=open                            # List open issues
sase bead list --status=ready --type=task                # List tasks awaiting triage
sase bead list --status=closed                          # List closed issues
sase bead search auth                                   # Search issues in every status
sase bead ready                                         # Show unblocked ready task beads
sase bead show beads-001                                # View issue details
sase bead read beads-001 -r "Need the scope"            # Audited agent read with a reason
sase bead ref add beads-001 research:202607/report.md   # Attach durable context
sase bead ref list beads-001 --resolve                  # List references and resolution state
sase bead ref rm beads-001 research:202607/report.md    # Detach a reference
sase bead update beads-001.1 --status=in_progress       # Set status; assignee stays unchanged
sase bead note beads-001.1 "Verified with just check"   # Append an attributed note
sase bead open beads-001.1                              # Reopen an issue
sase bead close beads-001.1                             # Close an issue
sase bead dep add beads-001.2 beads-001.1               # Add dependency
sase bead dep list beads-001.2 --format full            # Inspect dependency provenance
sase bead dep tree beads-001.2                          # Follow the blocking chain
sase bead dep rm beads-001.2 beads-001.1                # Remove a wrong dependency
sase bead blocked                                       # Show blocked issues
sase bead sync                                          # Export and stage JSONL in git
sase bead pages refresh                                # Preview regenerated bead pages
sase bead pages refresh --write                        # Regenerate, commit, and push bead pages
sase bead pages url beads-001.1                        # Print the hosted page URL when available
sase bead stats                                         # Project statistics
sase bead doctor                                        # Health check
sase bead doctor --fix-plan-archive                     # Backfill recoverable missing plan archives
sase bead doctor --fix-issue-prefix                     # Reset a leaked ProjectSpec-key issue prefix
sase bead doctor --fix-projection                       # Repair issues.jsonl from canonical events
sase bead work "$PLANS_ROOT/202605/epic.md" --dry-run   # Preview bead creation and launch waves
sase bead work "$PLANS_ROOT/202605/epic.md" --yes       # Create, link, and launch an epic plan
sase bead work "$PLANS_ROOT/202605/epic.md" --wait 'sase-s7.2,bead=sase-64.3' --yes
sase bead work epic-a epic-b -c 3 --yes                 # Capacity 3 for every new phase and land agent
sase bead work "$PLANS_ROOT/202605/epic.md" -C feature_epic --yes
sase bead work beads-001                                # Launch agents for an epic plan bead
sase bead work beads-002 --dry-run                      # Preview one standalone task worker
sase bead work beads-002 --yes                          # Launch one standalone task worker
sase bead work "$PLANS_ROOT/202605/epic.md" beads-002 --yes # Run targets in order, stopping at first error
```

## Bead ID Arguments

Every `sase bead` command argument that names an existing bead accepts either the full
ID or its shorthand suffix after the final dash. For example, `sase bead show 001`
resolves to `beads-001`, and dotted descendants work the same way:
`sase bead close 001.2` resolves to `beads-001.2`. Output, events, dependencies,
reference ownership, commit summaries, agent names, generated page paths, and JSON
payloads always use the canonical full ID.

Full IDs are still accepted unchanged, including IDs whose project prefix contains
dashes. If a shorthand suffix matches more than one bead, SASE rejects the command and
lists the candidate full IDs instead of choosing one arbitrarily.

When a full ID is not present in the current store, existing-bead operands fall back to
enabled SASE projects. SASE checks the current store first, and a local hit never reads
the project registry. After a local miss it looks for the exact full ID in each enabled
project's canonical bead store; project names, aliases, and stored prefixes are hints,
not proof that an ID exists. Shorthand suffixes remain local-only unless
`sase bead show -P/--project` pins a project. Every command that takes an existing bead
ID routes this way: `+1`, `apply-status`, `close` (including `--phases`), `create` (the
parent in `phase(<parent>)` or `plan(<file>,<parent>)`), `dep`, `epic-symbols`,
`history`, `note`, `open`, `pages refresh --bead`, `pages url`, `ref`, `rm`, `show`,
`snooze`, `update`, and `work`. Commands with no bead selector, such as `list`,
`search`, `ready`, `blocked`, and `stats`, keep their current-project scope, as do the
store-wide forms of `dep list`, `dep tree`, and `ref list`.

A routed command settles on one owning store before it does any work. Reads, writes, the
store commit, publication, and refresh all use that store, and project-specific context
follows the owner: `close` settles the owner's triage gates and checks the owner's
Justfile for `--epic-symbol` entries, `epic-symbols <id>` lists the owner's Justfile,
`ref list --resolve` resolves from the owner's workspace, `create` records the plan
reference relative to the owner's SDD store, and `work` launches in the owner's project
context. Free-form inputs stay relative to you: `@<path>` values and relative plan paths
resolve from the directory where you ran the command. A routed command never creates a
bead store in your current directory.

Every bead operand is resolved before anything is written. A batch that spans more than
one store, including a local shorthand next to another project's full ID, fails with
`multiple stores match the requested bead targets` before any event is recorded. For
example, `sase bead close bob-cli-1e --note done` can be run from another enabled
project, while `sase bead update bob-cli-1e sase-2 -s ready` is refused if those IDs
belong to different stores. A full ID that no readable store holds reports
`issue not found: <id>`, and an ID that exists in more than one enabled project's store
is reported as ambiguous with the candidate projects. If the likely owner (by name,
alias, or stored prefix) has no materialized or readable store on this machine, the
error names that project; an unrelated project with an unavailable store never blocks a
valid target. A routed mutation must also produce its store commit: if the owner's
auto-commit fails or creates nothing, the command fails with a
`routed bead mutation ... could not be committed for publication` diagnostic.

The active checkout belongs to the enabled project whose `WORKSPACE_DIR`, or a numbered
`_<N>` sibling of it, contains the current directory. Another project whose directory
key merely matches the workspace name, such as one auto-created for a `#git:<name>`
reference, cannot take over bead-store resolution. `sase doctor` warns
(`project.name_collisions`) when a project's `PROJECT_NAME` or alias case-insensitively
matches another project's directory key, `PROJECT_NAME`, or alias.

## Data Model

### Issue Types

| Type      | Description                                                    | ID Format                                 |
| --------- | -------------------------------------------------------------- | ----------------------------------------- |
| **Plan**  | Plan-like container with a tier; may be a child epic           | `{prefix}-{counter}` or `{parent_id}.{N}` |
| **Phase** | Sized executable child within an epic/plan bead                | `{parent_id}.{N}`                         |
| **Task**  | Independent, explicitly sized work item with no parent or tier | `{prefix}-{counter}`                      |

Plans are groupings that can optionally link to an SDD file via the `design` field.
Phases always belong to a parent plan and use hierarchical IDs (e.g., `beads-001.1`,
`beads-001.2`). Task beads are top-level, carry neither a parent nor a tier, and require
a size when newly created. A SASE feature-flag removal bead is a task bead of type
`flag` — see [Flag Bead Lifecycle](bead-lifecycles.md#flag-bead-lifecycle) — not a
fourth issue type. An epic proposed by a phase or land agent becomes a child plan bead
beneath the bead responsible for that agent. For example, phase `beads-001.2` can own
child epic `beads-001.2.1`; an epic proposed by the land agent can become the next
direct child such as `beads-001.3`.

Task beads are deliberately flat: the task creation form takes no plan path or parent
ID, and a task cannot carry a plan tier or Patch metadata. Use a task for independent
follow-up work that one worker can own. Use an epic and phase beads when the work needs
a validated plan, dependency waves, or a final land agent.

New task beads also require a [task type](#task-types) from the project's catalog:
`-T 'task(<slug>)'` plus any required `-f/--field` values. Bare `-T task` is an error
that lists the agent-creatable slugs.

The generic `sase bead update <task-id> --design <path>` command currently accepts
design metadata on a task, even though task creation does not. That metadata does not
give the task a parent or make task launch plan-backed: `sase bead work` still sends the
task description and notes to one worker. sase's TUI Plans pane shows the stored
reference but does not load its document into the task detail.

Plan beads carry a tier. The paths below are relative to the effective plans root. Use
`sase repo path plans` or `SASE_SDD_PLANS_DIR` to locate it without depending on the
storage layout.

| Tier   | Plans-root path | Behavior                                           |
| ------ | --------------- | -------------------------------------------------- |
| `plan` | `{YYYYMM}/*.md` | Normal non-epic implementation plan (`tier: tale`) |
| `epic` | `{YYYYMM}/*.md` | Executable multi-phase plan (`tier: epic`)         |

Epics use the plan syntax:

```bash
sase bead create --title "Epic" --type "plan(${SASE_SDD_PLANS_DIR}/202605/epic.md)" --tier epic \
  -w "Planning the feature breakdown"
```

### Task Types

`task_type` is an orthogonal flavor of discovered work. It is valid only on a task bead
and is distinct from the bead's issue type (`plan`, `phase`, `task`). New tasks require
a catalog slug; existing untyped legacy tasks stay readable and render as a dim
`untyped` chip. Feature-flag removal beads are task beads of type `flag`; list them with
`-T flag`, not `--type flag`.

```bash
sase bead create -T 'task(flake)' -t "Fix flaky retry" -z medium \
  -w "CI flakes on the retry path three times this week" \
  -f node_id=tests/foo.py::test_bar -f evidence=@evidence.md
sase bead task-type                  # agent-creatable catalog
sase bead task-type show flake       # fields, template, triage, provenance
sase bead list --task-type flake
sase bead list --task-type untyped   # legacy beads with no type
sase bead list -T flag               # feature-flag removal beads
```

`-T 'task(<slug>)'` selects the type. Repeatable `-f/--field k=v` supplies declared
fields; a value of `@<path>` is read from that file so long prose does not have to
survive the shell. Duplicate field keys are an error. The stored `description` stays
free text: the type's body template is rendered below it at display time, never merged
in. `sase bead update` has no `--task-type`; the type is immutable once set — close the
bead and recreate it to change the flavor.

When this machine does not have the providing plugin, `sase bead show` still succeeds
and prints the raw key/value pairs under a
`Task type: <slug> (not installed on this machine)` header. Creating a type that only
the committed snapshot knows names the package and the `sase plugin install` command.

The catalog is assembled from three sources, first wins: builtin specs,
`sase_task_types` plugin hooks, then `bead.task_types` project config. A
`use: <plugin>@<slug>` config entry deep-merges its sibling keys onto that slug; an
entry without `use:` defines a new slug and may not shadow a builtin. `sase memory init`
writes the committed catalog to `sase/task_types.json` and generates the short
`sase/memory/task_types.md` note from it for SASE-managed project repositories only, so
generated agent instructions stay a function of committed files rather than whichever
optional plugins happen to be installed. See
[Required plugins](../config/prompts-and-tools.md#plugins) and
[Task-type plugins](../../plugins.md#task-type-plugins).

Suppress a builtin for a project or the whole machine with `use: <plugin>@<slug>` plus
`agent_creatable: false`; existing beads of that type keep rendering normally. The
`use:` prefix always names the type's original provider (`builtin` for a builtin), no
matter how many layers have already overridden the slug. A machine-global entry in
`~/.config/sase/sase.yml` applies to every project on the machine, and a project's own
`sase/sase.yml` entry wins over it.

Every CLI, sase's TUI, bead-page, and gate-preview surface routes the colored type chip
through one presentation module. Builtins use hand-tuned glyphs (`⨯` bug, `⚙` ci, `✦`
feature, `≈` flake, `▤` memory); a type that declares none gets a stable hash-derived
color.

<a id="per-type-triage-bar"></a>

A type also carries its own triage bar. `triage.min_plus_ones` is the number of
independent [`+1`](bead-triage.md#task-corroboration-1) reports a ready bead of that
type needs before it earns a `TaskTriage` gate. A bead resolves its bar one of two ways:

- **Typed, and this machine has the type registered** — the type's own
  `triage.min_plus_ones` wins. The spec default is `0`; among the builtins, `flake`
  ships `3` because a test that failed once is the case most often misread as a real
  defect, `bug` ships `1` because a defect found while doing something else deserves one
  independent reproduction before it interrupts anyone, and `ci`, `feature`, and
  `memory` ship `0`.
- **Untyped, or typed with a slug this machine does not have registered** — the
  configured [`bead.task_triage.min_plus_ones`](../config/automation-behavior.md#bead)
  is the fallback. It ships as `1`.

Those two defaults differ on purpose, so do not read the spec default of `0` as "the
default bar is zero": a legacy untyped bead needs one `+1` out of the box, while a typed
`ci` bead needs none. `sase bead task-type show <slug>` prints the effective bar under
`TRIAGE`.

<a id="status-lifecycle"></a> Moved to
[Bead lifecycles](bead-lifecycles.md#status-lifecycle). <a id="flag-bead-lifecycle"></a>
Moved to [Bead lifecycles](bead-lifecycles.md#flag-bead-lifecycle).
<a id="bead-claim-lifecycle"></a> Moved to
[Bead lifecycles](bead-lifecycles.md#bead-claim-lifecycle).
<a id="standalone-task-workflow"></a> Moved to
[Bead triage](bead-triage.md#standalone-task-workflow).
<a id="snoozing-a-task-bead"></a> Moved to
[Bead triage](bead-triage.md#snoozing-a-task-bead). <a id="task-corroboration-1"></a>
Moved to [Bead triage](bead-triage.md#task-corroboration-1). <a id="close-history"></a>
Moved to [Bead triage](bead-triage.md#close-history). <a id="dependencies"></a> Moved to
[Bead triage](bead-triage.md#dependencies).
<a id="discovered-follow-up-capture-and-triage"></a> Moved to
[Bead triage](bead-triage.md#discovered-follow-up-capture-and-triage).
<a id="external-issue-mirroring"></a> Moved to
[Bead mirroring](bead-mirroring.md#external-issue-mirroring).
<a id="artifact-references"></a> Moved to
[Bead artifacts](bead-artifacts.md#artifact-references). <a id="attachments"></a>
<a id="storage-tiers-and-privacy"></a> <a id="attachment-visibility"></a>
<a id="from-the-beads-pane"></a> <a id="viewing"></a>
<a id="troubleshooting-badges"></a> <a id="mixed-fleet-upgrades"></a>
<a id="large-object-store-rclone"></a> Moved to
[Bead attachments](bead-attachments.md#attachments). <a id="creation-reason"></a> Moved
to [Beads](#creation-reason). <a id="creation-time-presentation"></a> Moved to
[Beads](#creation-time-presentation).

## Creation Reason

Every new bead stores a filing reason: why the bead exists. The title names the work,
and the description holds scope and evidence. Close text from `sase bead close -r` and
the audited reason on `sase bead read -r` are separate fields.

`sase bead create` requires `-w/--reason` on plan, phase, and task beads. The value is
trimmed, must be non-blank, and may be at most 2000 characters. A value of `@<path>` is
read from that file, the same way `--description` works. A missing, blank, or over-long
reason is rejected before the store changes.

The reason is fixed when the bead is filed. `sase bead update` has no flag for it, and
the Beads pane editor does not offer the field.

Beads filed before this field existed store an empty reason. Human detail output omits
the section for those beads, and JSON omits the key.

`sase bead show` and `sase bead read` print a `CREATION REASON` section immediately
before `DESCRIPTION` when the reason is non-empty. That prose wraps with `--wrap` and
takes the same rich highlighting as the description. `--format json` includes
`issue.creation_reason` only when the stored reason is non-empty.
[`sase bead search`](bead-cli-query.md#sase-bead-search-query) indexes the same text as
the `creation_reason` field. A hit that matches only that field still lists the bead,
and JSON reports `creation_reason` in `matched_fields`. Compact search output does not
print a `creation_reason:` snippet line for that hit.

In sase's TUI, the Beads pane detail shows a `Creation reason` property and a
`**Creation reason:**` line in the preview. `n` opens the create modal for a standalone
task in the selected project; its "Why this bead was filed" field is required and uses
the same 2000-character limit (`Ctrl+S` creates, `Esc` cancels). On the Agents tab, a
bead the selected agent created shows the reason as a `why:` line under that bead in
`SASE CONTEXT / ARTIFACTS`. A truncated index copy adds `… full reason in bead detail`.
An assigned bead the agent did not create has no filing-reason line.

Some flows file beads without asking you for `-w`. Approving an epic records
`Approved epic plan <plan-ref> requests this work` on the epic bead and
`Epic plan <plan-ref> defines phase <id> as one work unit` on each phase.
`sase flag new` records `Flag '<key>' needs a removal-tracked bead`. External-issue
mirroring records `Mirror upstream <ref> as a tracked bead`.

The TaskTriage gate preview does not include the filing reason. Open the bead with
`sase bead show` or the Beads pane to read it.

## Creation Time Presentation

Every bead's `created_at` is `TEXT NOT NULL` in the store schema and is populated on
every bead, always in aware-UTC ISO form (`2026-04-28T01:34:17Z`). Every surface that
renders a bead also renders when it was created, through the single shared module
`src/sase/bead_time_presentation.py`, so the glyph, accent color, wording, and timezone
agree everywhere.

Two glyphs carry the vocabulary, both rendered in the muted teal accent `#5FAFAF`,
deliberately distinct from the bead identity colors (gold ids, blue phase, purple task)
so creation time reads as provenance metadata rather than competing with the title:

| Glyph | Meaning      |
| ----- | ------------ |
| `⧖`   | created      |
| `✎`   | last updated |

Three density tiers, selected per surface:

- **Full** — a labeled row on detail surfaces:
  `⧖ Created   2026-04-28 01:34:17 EDT · 3mo ago`
- **Compact** — a glyph-prefixed cell on single-line rows: `⧖ 3mo`
- **Data** — the raw stored ISO string, unformatted, on JSON/wire surfaces.

**The live-vs-persisted rule** governs which form a surface may use: a relative age may
appear only on surfaces that are re-rendered on every read (sase's TUI panes, the BEAD
lane, CLI terminal output). Any surface whose bytes are persisted, hashed, or
reconstructed for validation — the TaskTriage gate preview, bead pages, JSON, the mobile
wire — renders the absolute timestamp only (`relative=False`), because a relative age
would make those bytes drift as the bead ages and break byte-stability or gate
validation.

Unparseable or empty values render an honest `unknown` placeholder rather than a
fabricated time; elapsed time is clamped at zero so clock skew renders `now` instead of
a negative age.

Any new bead-rendering surface must format creation and update time through
`sase.bead_time_presentation` rather than formatting a timestamp itself. Known,
deliberate exceptions where a bead-rendering surface does not show its own creation
time:

- The dependency-edge `added <ts> by <who>` line in
  `sase bead dep list`/`sase bead dep tree` — the dependency edge's own timestamp, not
  the bead's; the bead's creation time appears in the same row as a separate `⧖` cell.
- The artifact-reference completion menu's shared age column, which renders `updated_at`
  for both bead and agent rows; repointing it would change agent-row semantics for no
  gain, so the bead's creation age instead rides in the glyph-labeled detail string.
- The bead pages Mermaid lineage graph node labels, which stay minimal
  (`id: title [status]`) for diagram readability; the full instant is one click away in
  the same page's identity block.

`tests/test_bead_time_surface_coverage.py` enumerates every covered surface and asserts
each renders a creation time for a fixture bead, so a future surface cannot silently
regress this contract.

## Related

- [Bead lifecycles](bead-lifecycles.md)
- [Bead triage](bead-triage.md)
- [Bead storage](bead-storage.md)
