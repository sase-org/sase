# Bead Issue Tracking

Bead is a lightweight, git-native issue tracking system built into sase. It uses Rust-backed event storage,
query/reduction, and mutation logic through the required `sase_core_rs` extension, with generated JSONL compatibility
projections for older tooling (inspired by [Fossil](https://fossil-scm.org/)). Issues are organized into plan-like
containers and executable child phases. Plan beads can represent ordinary plans or executable epics through their `tier`
metadata.

![Bead issue model, storage sync, and epic wave execution](images/bead-epic-work-infographic.png)

## Table of Contents

- [Quick Start](#quick-start)
- [Data Model](#data-model)
  - [Issue Types](#issue-types)
  - [Status Lifecycle](#status-lifecycle)
  - [Dependencies](#dependencies)
- [Storage](#storage)
  - [Directory Structure](#directory-structure)
  - [Event Log + Compatibility Projections](#event-log-compatibility-projections)
  - [Sync Mechanism](#sync-mechanism)
- [CLI Commands](#cli-commands)
- [Rust Backend](#rust-backend)
- [Current Checkout Source Of Truth](#current-checkout-source-of-truth)
- [ACE TUI Integration](#ace-tui-integration)

## Quick Start

```bash
PLANS_ROOT=$(sase repo path plans)
sase bead init                                          # Initialize beads in current project
sase bead create -t "New feature" --type "plan(${PLANS_ROOT}/202605/feature.md)" --tier plan
sase bead create -t "Epic" --type "plan(${PLANS_ROOT}/202605/epic.md)" --tier epic
sase bead create -t "Sub-task" --type "phase(beads-001)" --size small # Create a sized phase
sase bead list                                          # List open and in-progress issues
sase bead list --status=open                            # List open issues
sase bead list --status=closed                          # List closed issues
sase bead search auth                                   # Search open, in-progress, and closed issues
sase bead ready                                         # Show issues ready to work on
sase bead show beads-001                                # View issue details
sase bead update beads-001.1 --status=in_progress       # Claim an issue
sase bead open beads-001.1                              # Reopen an issue
sase bead close beads-001.1                             # Close an issue
sase bead dep add beads-001.2 beads-001.1               # Add dependency
sase bead blocked                                       # Show blocked issues
sase bead sync                                          # Export and stage JSONL in git
sase bead stats                                         # Project statistics
sase bead doctor                                        # Health check
sase bead work "$PLANS_ROOT/202605/epic.md" --dry-run   # Preview bead creation and launch waves
sase bead work "$PLANS_ROOT/202605/epic.md" --yes       # Create, link, and launch an epic plan
sase bead work beads-001                                # Launch agents for an epic plan bead
```

## Data Model

### Issue Types

| Type      | Description                                          | ID Format                                 |
| --------- | ---------------------------------------------------- | ----------------------------------------- |
| **Plan**  | Plan-like container with a tier; may be a child epic | `{prefix}-{counter}` or `{parent_id}.{N}` |
| **Phase** | Sized executable task within an epic/plan bead       | `{parent_id}.{N}`                         |

Plans are groupings that can optionally link to an SDD file via the `design` field. Phases always belong to a parent
plan and use hierarchical IDs (e.g., `beads-001.1`, `beads-001.2`). An epic proposed by a phase or land agent becomes a
child plan bead beneath the bead responsible for that agent. For example, phase `beads-001.2` can own child epic
`beads-001.2.1`; an epic proposed by the land agent can become the next direct child such as `beads-001.3`.

Plan beads carry a tier. The paths below are relative to the effective plans root. Use `sase repo path plans` or
`SASE_SDD_PLANS_DIR` to locate it without depending on the storage layout.

| Tier   | Plans-root path | Behavior                                           |
| ------ | --------------- | -------------------------------------------------- |
| `plan` | `{YYYYMM}/*.md` | Normal non-epic implementation plan (`tier: tale`) |
| `epic` | `{YYYYMM}/*.md` | Executable multi-phase plan (`tier: epic`)         |

Epics use the plan syntax:

```bash
sase bead create --title "Epic" --type "plan(${SASE_SDD_PLANS_DIR}/202605/epic.md)" --tier epic
```

### Status Lifecycle

| Status        | Icon | Description               |
| ------------- | ---- | ------------------------- |
| `open`        | `○`  | Not started               |
| `in_progress` | `◐`  | Currently being worked on |
| `closed`      | `✓`  | Completed or abandoned    |

Status can transition freely between any values via `sase bead update --status=<status>`. `sase bead open <id>` is a
shortcut for `sase bead update <id> --status=open`.

### Dependencies

Dependencies are one-way relationships: issue A **depends on** issue B. An issue is:

- **Ready** if it is `open` and all its dependencies are `closed`.
- **Blocked** if it has at least one dependency with status `open` or `in_progress`.

## Storage

### Directory Structure

When the workspace provider declares in-tree storage, as the built-in `bare_git` provider does:

```
sdd/beads/
  config.json           # Configuration (issue prefix, counter, owner)
  events/
    manifest.json       # Event-store schema and migration metadata
    streams/
      <root-id>.jsonl   # Canonical append-only event stream
  issues.jsonl          # Generated compatibility projection
  beads.db              # SQLite compatibility cache (gitignored)
```

Providerless local storage and legacy single-sidecar storage use `.sase/sdd/beads/` with the same structure. Split
sidecar storage uses `beads/` at the root of the active workspace's auto-cloned `--plans` repository. Local storage uses
the primary workspace; both sidecar layouts use the active workspace clone and record provider/remote metadata in the
primary workspace's `.sase/sdd-store.json`.

Normal bead commands read and write one store for the active checkout. In in-tree mode, canonical bead state lives in
the current checkout's `sdd/beads/events/**` event store plus `sdd/beads/config.json`. Providerless local commands route
to the primary workspace's `.sase/sdd/beads/` store. Sidecar-policy commands first materialize the provider store, then
route to the active workspace clone so an agent in workspace `#N` writes either its matching `.sase/sdd/` checkout or
its `sase/repos/plans/beads/` directory. If the event store is absent, reads fall back to legacy `issues.jsonl`.
Numbered sibling workspaces and legacy stores are not merged into normal `sase bead` reads.

### Event Log + Compatibility Projections

Rust owns the bead storage/query/mutation path. The append-only event streams are the canonical git-portable state.
`issues.jsonl` remains a generated compatibility projection, and `beads.db` remains a local compatibility cache. They
are kept in sync:

- **Writes** append canonical Rust events first, then regenerate `issues.jsonl` and refresh `beads.db`.
- **Reads** prefer `events/manifest.json` plus `events/streams/*.jsonl`, falling back to legacy `issues.jsonl` only when
  no event store is present.
- **Fresh clones** read directly from the tracked event streams and can rebuild the compatibility mirrors on demand.

The `.gitignore` excludes `beads.db*` files. The event store, `issues.jsonl`, and `config.json` are tracked in git.

### Sync Mechanism

`sase bead sync` regenerates the compatibility projection from the canonical event store and stages the bead state in
the owning git repo, including `events/**`, `issues.jsonl`, and `config.json`. The projection contains one JSON object
per line, sorted by issue ID for clean diffs.

When both stores exist, the event store wins. Manual edits to `issues.jsonl` do not change command output unless the
event store is absent.

## CLI Commands

With no subcommand, `sase bead` defaults to `sase bead list` with default options. Use the explicit `sase bead list`
form when passing list filters.

### `sase bead init`

Initialize the bead store for the current project. In effective in-tree SDD mode this is `sdd/beads/`; local and legacy
separate-repo modes use `.sase/sdd/beads/`; split sidecar mode uses `beads/` in the `--plans` repository.

### `sase bead create`

Create a new issue.

| Flag                | Required | Description                                                                                                                                                                                                                          |
| ------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `-t, --title`       | yes      | Issue title                                                                                                                                                                                                                          |
| `-T, --type`        | yes      | Bead type: `plan(<file>)`, `plan(<file>,<parent>)`, or `phase(<parent_id>)`                                                                                                                                                          |
| `-d, --description` | no       | Issue description                                                                                                                                                                                                                    |
| `-a, --assignee`    | no       | Assignee name                                                                                                                                                                                                                        |
| `--tier`            | no       | Plan-bead tier: `plan` or `epic`                                                                                                                                                                                                     |
| `-c, --changespec`  | no       | Attach a ChangeSpec name to a plan bead                                                                                                                                                                                              |
| `-b, --bug-id`      | no       | Bug ID for the attached ChangeSpec; requires `--changespec`                                                                                                                                                                          |
| `-m, --model`       | no       | Model used when this bead is launched. Provider-qualified (e.g. `codex/gpt-5.6-sol`) or a configured local alias (e.g. `#pro`). On epic plan beads this becomes the land-agent model; on phase beads it is the per-phase work model. |
| `-z, --size`        | no       | Phase size: `small`, `medium`, or `large`. Valid only on phase beads; an omitted legacy/manual value behaves as `small`.                                                                                                             |

ChangeSpec metadata is valid only on plan beads. It is used by the epic-approval and `sase bead work` flows to keep plan
beads linked to the ChangeSpec they are intended to produce.

### `sase bead list`

List issues with optional filtering. Without `--status`, the command lists `open` and `in_progress` issues; pass
`--status=closed` when you need closed history. When the default open/in-progress query is empty and no explicit
`--status` was given, the command falls back to listing closed beads. `--status`, `--type`, and `--tier` are repeatable.

| Flag           | Values                          | Description                                                                           |
| -------------- | ------------------------------- | ------------------------------------------------------------------------------------- |
| `-s, --status` | `open`, `in_progress`, `closed` | Filter by status (repeatable)                                                         |
| `-t, --type`   | `plan`, `phase`                 | Filter by type (repeatable)                                                           |
| `--tier`       | `plan`, `epic`                  | Filter by plan-bead tier                                                              |
| `-n, --limit`  | integer                         | Maximum beads to print; closed listings default to the newest 20, `0` means unlimited |

Open/in-progress listings are unlimited by default. Whenever the final status scope includes `closed` and `--limit` is
omitted, only the newest 20 beads print; pass `--limit 0` for the full closed history.

### `sase bead search <query>`

Find beads whose indexed text fields contain a case-insensitive literal substring. This is substring search, not regex
or glob matching. Current indexed fields include ID, title, description, notes, design/plan path, owner, assignee,
model, phase size, ChangeSpec name/bug ID, status, type, and tier; timestamps are not searched. Unlike `sase bead list`,
search includes `open`, `in_progress`, and `closed` beads by default, so it is the quickest way to recover older
context.

Compact output prints each matching bead with a short snippet. For multi-line fields such as descriptions or notes, the
snippet uses the line that matched the query when possible instead of always showing the first line. JSON output exposes
the exact `matched_fields` list for each result.

```bash
sase bead search auth
sase bead search auth --format json
sase bead search auth --format full --limit 3
sase bead search auth --status open --type phase
sase bead search auth --type plan --tier epic
```

| Flag           | Values                          | Description                                     |
| -------------- | ------------------------------- | ----------------------------------------------- |
| `-c, --color`  | `auto`, `always`, `never`       | Color mode for compact output                   |
| `-f, --format` | `compact`, `json`, `full`       | Output format; defaults to `compact`            |
| `-n, --limit`  | non-negative integer            | Maximum results; omitted or `0` means unlimited |
| `-s, --status` | `open`, `in_progress`, `closed` | Filter by status (repeatable)                   |
| `--tier`       | `plan`, `epic`                  | Filter by plan-bead tier (repeatable)           |
| `-t, --type`   | `plan`, `phase`                 | Filter by type (repeatable)                     |

### `sase bead show <id>`

Display complete details for an issue including status, type, tier, parent lineage, dependencies, blockers, description,
notes, ChangeSpec metadata, model, and linked plan path. Phase beads show their effective size (`small` for legacy beads
without a stored size). Any bead's children are grouped as phases (with status and size) and child epics (with tier and
status), including child epics owned by a phase bead. Nested beads show their complete lineage back to the root plan.

### `sase bead ready`

Show issues that are ready to work on: `open` status with all dependencies `closed`.

### `sase bead open <id>`

Reopen an issue by setting its status to `open`. This is equivalent to `sase bead update <id> --status=open`.

### `sase bead update <id>`

Update one or more fields on an issue.

| Flag                | Description                                               |
| ------------------- | --------------------------------------------------------- |
| `-s, --status`      | Change status                                             |
| `-t, --title`       | Change title                                              |
| `-d, --description` | Change description                                        |
| `-n, --notes`       | Change notes                                              |
| `-D, --design`      | Change plan path                                          |
| `-a, --assignee`    | Change assignee                                           |
| `--tier`            | Change plan tier                                          |
| `-m, --model`       | Change the launch model. Pass an empty string to clear.   |
| `-z, --size`        | Change a phase bead's `small`, `medium`, or `large` size. |

### `sase bead close <id> [<id2> ...]`

Close one or more issues.

Closing a plan bead also closes all descendant phase and child-plan beads recursively. Use this intentionally: phase
agents should close only their assigned phase bead, not the parent epic.

Closing a delegated child plan/epic also closes its parent phase automatically once every child of that phase is closed.
This upward cascade continues only through phase parents and never auto-closes a parent plan/epic; the parent land agent
retains that responsibility. Removing a child epic does not trigger the cascade, so its phase stays open and can be
scheduled again on retry.

| Flag           | Description                |
| -------------- | -------------------------- |
| `-r, --reason` | Optional close reason text |

### `sase bead rm <id>`

Remove an issue and recursively cascade-delete all its descendants, including phases nested beneath child epics. This is
irreversible.

### `sase bead dep add <issue> <depends_on>`

Add a dependency: `<issue>` depends on `<depends_on>`. The issue becomes blocked if the dependency is not yet closed.

### `sase bead blocked`

Show all issues that have at least one active (non-closed) blocker.

### `sase bead sync`

Regenerate the compatibility projection from the canonical event store and stage bead state in git. It does not create a
commit; the staged event/projection files are included in the next normal project or SDD commit.

| Flag           | Description                                   |
| -------------- | --------------------------------------------- |
| `-s, --status` | Check whether bead state has unstaged changes |

### `sase bead stats`

Show project statistics: total, open, in-progress, and closed counts, plus plan and phase counts.

### `sase bead doctor`

Run health checks on the beads database. Checks for:

- Missing `config.json`, event store, legacy projection, or compatibility cache
- Projection drift between canonical events and `issues.jsonl`
- Invalid events or unreduced orphan phase records
- Uncommitted bead-state changes
- Orphan children (phase or nested-plan beads whose parent is missing)

If bead commands fail before opening a store, run `sase core health` first. It verifies that the required `sase_core_rs`
extension is importable and exposes the representative bead CLI binding used by the fast path.

### `sase bead onboard`

Display a quick-start guide with common command examples.

### `sase bead work <target>`

Create or resume an epic from a validated Markdown plan, or launch an existing epic-tier plan bead. A target is treated
as a plan file when it ends in `.md`, contains a path separator, or names an existing file; other targets are bead IDs.
Both modes use the same launcher to run one agent per non-closed, non-delegated phase plus a final land agent.

Plan-file mode is the canonical epic-approval entry point. It:

1. Validates the file against the epic plan schema and reports the complete diagnostics on failure.
2. Resolves the project's SDD and bead stores, initializing the bead store when needed.
3. Archives the plan under the resolved `{YYYYMM}/` plans directory and commits it.
4. Resumes the linked epic when the archived plan already has a valid `bead_id`.
5. Otherwise creates the epic plan bead from the plan's `title`, `goal`, top-level `model`, optional `parent_bead`, and
   optional ChangeSpec metadata; creates phase beads with their authored sizes in `phases[]` order; wires every
   `depends_on` edge; and commits the new `bead_id` link.
6. Invokes the existing bead-ID launch path.

A missing phase description becomes a deterministic pointer to the plan and phase ID. A linked `bead_id` that no longer
exists fails with instructions to remove the stale link or restore the bead store. Failures before any runner is spawned
remove the newly-created epic and children and restore the plan link. Once a runner has spawned, the linked epic and its
readiness state are preserved for recovery; partial runners are terminated, while a failure committing bead state after
all agents started leaves them running. Every plan-file failure after archiving prints the exact
`sase bead work ... --yes` command to resume.

When an epic-tier plan is proposed from bead work, `sase plan propose` automatically stamps `parent_bead` from the phase
agent's `SASE_PHASE_BEAD_ID`, or from the land agent's `SASE_EPIC_BEAD_ID`. Plan-file mode resolves that bead and
creates the new epic beneath it, yielding recursive IDs such as `beads-001.2.1`; an unresolved parent fails with a
remedy instead of silently creating a top-level epic. `--parent <bead-id>` overrides the authored association, while
`--parent top-level` explicitly creates an unparented epic. The override applies only to plan-file targets.

`--dry-run` plan-file mode validates and resolves the stores, previews the archive destination, parented epic ID,
authored beads, routed models, and dependency waves, and does not write files, create beads, reserve names, or launch
agents. `--json` prints one stable object for scripting; successful human output always ends with a grep-friendly
`Epic: <id>` line used by approval hosts.

Once an epic bead exists, the shared launch path:

1. Validates that `<epic_id>` resolves to an issue of type `plan` with `tier=epic`. If the plan is already marked
   `is_ready_to_work`, the command treats the run as a retry and schedules any remaining non-closed phases. A phase that
   owns a non-closed child plan/epic is delegated work already in flight and is skipped until that child closes or is
   removed; retries therefore do not launch a duplicate phase agent.
2. On a confirmed launch, force-reuses the deterministic bead-work names — `<epic_id>.<N>` (for each open phase),
   `<epic_id>.land` (for the land agent), and the legacy `<epic_id>` land-agent name — by wiping any prior owner of
   those names, whether that owner is a completed, dismissed, or planned reservation or a still-live agent (live owners
   are terminated). This also covers owners that hold the name only as a `workflow_name`. If the forced-reuse cleanup
   cannot complete (a wipe fails or a name is still reserved afterward), the command aborts before mutating any bead
   state. `--dry-run` performs no cleanup; it only warns which live agents a real launch would force-reuse.
3. Flips the epic plan bead's `is_ready_to_work` flag to `True` when it was not already ready.
4. Builds a Kahn-wave schedule from the epic's schedulable open phase children, respecting dependencies and excluding
   delegated phases with an open child plan/epic. When every remaining phase is delegated, only the land agent is
   launched and remains parked behind the phase beads.
5. Associates each rendered worker with exactly one bead in its `%id`: the first phase uses its full agent name plus
   `bead=<phase-id>` beside the separate clan declaration, later phases combine their suffix, `clan=<epic-id>`, and
   `bead=<phase-id>`, and the land agent combines `land`, the clan, and `bead=<epic-id>`. Rendering and launch approval
   do not change phase or epic status.
6. Hands a single `---`-separated multi-prompt to the agent launcher. Each per-phase agent is spawned with name
   `<epic_id>.<N>` and references the [`work_phase_bead`](xprompt.md#available-tags) xprompt; a final land agent named
   `<epic_id>.land` references the [`land_epic`](xprompt.md#available-tags) xprompt. Every segment joins clan
   `<epic_id>` and assigns that whole clan to tribe `@epic` with the single `%clan(<epic_id>, tribe=epic)` directive.
   Each phase dependency becomes both a `%w` wait on the blocker phase-agent name and a `%w(bead=<blocker-phase-id>)`
   closure wait. The land agent likewise waits on every launched phase agent and on every authored phase bead, including
   already-closed or currently delegated phases. Requiring both conditions prevents a phase that delegated to a child
   epic from releasing dependents merely because its original agent finished; the child epic must land and close the
   parent phase first. A failed or killed phase keeps dependents and the land agent parked until its agent name is
   retried successfully and its bead closes. Small phases launch directly with `%model:@small_phase_worker`; medium
   phases use `%model:@medium_phase_worker` and append `#plan` after their work reference; large phases likewise append
   `#plan` and use `%model:@large_phase_worker`. A stored phase `model` always wins over the size-derived alias, and a
   missing legacy size behaves as `small`. The land agent emits `%model:<value>` when the epic plan bead has a stored
   `model`. Without one, it emits `%model:@epic_lander` below `bead.big_epic_phase_threshold` and
   `%model:@big_epic_lander` at or above the threshold (default `5`), using the total authored phase count even when
   resumed work has already-closed phases. Normal landers fall through `@epic_lander` to `@default`, while landers
   selected by the threshold fall through `@big_epic_lander` to provider-aware `@smartest`. Small phases fall through
   `@small_phase_worker` to the load-balanced `@cheaper` pool, medium phases fall through `@medium_phase_worker` to
   `@default`, and large phases fall through `@large_phase_worker` to `@smartest`. The independent `@cheapest` pool is
   available for explicit use but has no automatic consumer. Builtin aliases can be configured under
   `llm_provider.model_aliases.builtin`. Each phase segment and the final land-epic segment carries bare `%auto`, so
   submitted implementation and landing plans are auto-approved. An agent may author a tale or an epic as needed; the
   plan's authored `tier` selects the corresponding automatic follow-up path. Each runner waits for its agent and bead
   dependencies, prepares its workspace, then atomically claims its associated bead immediately before model execution.
   The claim sets `status=in_progress` and assigns the runner name; parallel workers claim independently, and the land
   runner claims the epic only after all phase waits. Each segment uses a force-reuse
   `%id(!<agent_name>, bead=<bead-id>)` form (with `clan=` on join segments), so re-running `sase bead work` after a
   killed or failed run wipes stale name owners before relaunch — the command is safe to retry.

When a phase agent auto-approves an epic-tier implementation plan, that child epic is created beneath the phase and the
phase remains open while delegated work runs. Landing the child epic triggers the upward close cascade described above,
which closes the phase and lets its bead-gated dependents proceed. Until then, parent-epic retries skip that delegated
phase. The land agent now genuinely requires every phase bead to close; if a phase crashes before closure, retry or
close that phase explicitly rather than expecting landing to sweep it up.

| Flag            | Description                                                                                   |
| --------------- | --------------------------------------------------------------------------------------------- |
| `-n, --dry-run` | Validate and preview plan archiving, bead creation, model routing, and waves without mutation |
| `-j, --json`    | Print one machine-readable result object; also skips interactive confirmation                 |
| `-P, --no-push` | Commit plan and bead state locally but skip post-commit pushes                                |
| `-p, --parent`  | Override a plan file's `parent_bead`; pass `top-level` to force an unparented epic            |
| `-y, --yes`     | Skip the launch confirmation prompt                                                           |

The work xprompts are resolved by `XPromptTag` (tag-based lookup), so a project-local or user-defined xprompt with the
matching tag overrides the built-in. For epic-tier work, every phase and land segment carries bare `%auto`, so spawned
agents can auto-approve submitted tale or epic plans and follow the path selected by the authored `tier`, without a
human-in-the-loop checkpoint between dependency waves.

When the epic plan bead is attached to ChangeSpec metadata (`--changespec` / `--bug-id`), `sase bead work` preserves the
current project's VCS context in the generated prompt. The first phase segment targets the project reference and adds a
`#pr` reference for the ChangeSpec, while later phase and land segments target the ChangeSpec ref directly. For
non-ChangeSpec epics launched from a known SASE workspace, each segment is still prefixed with the detected VCS workflow
and project name (for example `#git:sase` or `#gh:sase-org/sase`). If the current directory is not associated with a
SASE project, the prompts are left unprefixed and run in the caller's normal launch context.

If launching fails before any runner is spawned, the command restores `is_ready_to_work` only when this attempt set it
and commits that recovery using the selected push policy. If launching fails partway through, it SIGTERMs spawned
children through identity-aware cleanup, keeps readiness and any durable runner-owned claims, and commits the
recoverable state. An epic that was already ready remains ready in either case.

After the agents launch successfully, `sase bead work` commits readiness and other launch-owned bead metadata when the
beads directory belongs to a git repository and canonical/projection files changed. Runner-owned claims are committed by
the runners instead. This commit does not include code produced later by the spawned agents. Epic launches use the
subject `chore: mark bead work launched for <id>`. If the git commit fails, the command reports that agents were already
launched and exits non-zero so the operator can commit or repair the bead state explicitly. Dry runs and stores outside
git do not create a commit.

When that commit succeeds and `bead.push_after_commit` is `true` (the default), `sase bead work` follows it with
`git push` so the launched-work record reaches the remote without a manual follow-up step. The push inherits the
caller's stdin/stdout/stderr, so interactive credential prompts still work. If the repository has no remote configured,
the push is skipped silently — the local commit stands on its own. If `git push` fails (for example because the remote
rejected the update), the failure is reported as a warning only: the bead-launch commit is preserved on the local branch
and the warning text includes the manual `git push` invocation to retry.

Set `bead.push_after_commit: false` in `~/.config/sase/sase.yml` to disable the auto-push — useful for local-only
checkouts, or when you would rather batch the bead-launch commit with later commits before pushing. Set it to `async` to
keep auto-pushing but move the push off the critical path: `sase bead work` launches a detached background `git push`
and returns immediately, printing the log file where the background push records its result. The background push is
non-interactive (its stdin is closed), so it cannot prompt for credentials; failures are written to that log instead of
warning inline. Pass `--no-push` (`-P`) to `sase bead work` to skip the push for a single invocation regardless of the
configured mode.

## Rust Backend

The bead data model, event reducer, JSONL/config codecs, compatibility-cache refresh, mutation transactions, ID
allocation, deterministic work-plan DAG, and common CLI output planning are implemented in `sase-core` and exposed
through `sase_core_rs`. Python keeps the host logic that belongs in the application layer: locating the active bead
store, relativizing plan paths, resolving VCS context and xprompts for `sase bead work`, prompting the user, launching
agents, rolling back failed launches, and incrementing telemetry counters.

Common `sase bead` commands dispatch through an early CLI fast path before the full top-level parser is built. Help text
and host-coupled commands still fall through to the normal Python parser/handlers where needed.

Use these checks when changing bead internals:

```bash
sase core health -j
pytest tests/test_bead tests/test_core_facade/test_bead_read.py tests/test_core_facade/test_bead_mutation.py
just rust-check
just bead-perf-smoke
```

## Current Checkout Source Of Truth

In in-tree mode, every `sase bead` read and mutation command uses the current checkout's `sdd/beads/events/**` event
store and `sdd/beads/config.json`, with `issues.jsonl` used only as a fallback when events are absent. Running the
command in `myproject/` reads that checkout's bead state; running it in `myproject_2/` reads `myproject_2/sdd/beads/`.
The CLI does not merge sibling workspace stores, and duplicate IDs in another checkout do not override the active
checkout's records.

ID allocation also uses only the active store's `config.json` and canonical event state. If a sibling checkout has not
pulled or merged the latest bead state, it may allocate IDs based on its local state; sync bead changes through the
normal VCS workflow when several agents are coordinating on the same project.

Cross-project helper surfaces, such as mobile/editor bead pickers, may inspect one canonical store per known project,
but they still do not merge numbered sibling workspaces or legacy bead stores for the same project.

## ACE TUI Integration

### Plan File Linking

When creating a plan bead with `--type plan(PATH)`, the file path is stored in the `design` field. The ACE TUI can
navigate from a bead to its linked SDD file.

For SDD-generated epics, `PATH` should be the shared plan reference emitted by the plan approval flow: `sdd/plans/...`
in in-tree mode, `.sase/sdd/plans/...` in local and legacy separate-repo modes, or `<YYYYMM>/...` in the split `--plans`
repository. SASE resolves those references against the effective SDD root when launching bead work. For manual commands
and prompts, `SASE_SDD_PLANS_DIR` or `sase repo path plans` is less ambiguous than guessing which relative prefix
applies.

### Plan Approval Flow

The plan approval popup in ACE includes normal approval and **E** (Epic) actions. Normal approval saves to the resolved
SDD `plans/` directory with `tier: tale`. Epic approval first submits a deduplicated tracked task that runs
`sase bead work <plan-file> --yes` from the project's primary workspace, then records that the host owns the launch in
the planner response. The Tasks tab shows live command output and provides kill support; success back-fills the epic ID
and committed plan path into planner metadata. If task submission fails, the response omits host ownership and the
planner runs the same canonical command as a subprocess.

`sase plan approve --kind epic` runs the command in the foreground. Headless approval callers use a detached worker with
a launch log and completion notification by default. The planner writes its prompt snapshot, finishes as
`EPIC APPROVED`, and does not race the command for ownership of the epic plan file.
