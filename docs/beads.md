# Bead Issue Tracking

Bead is a lightweight, git-native issue tracking system built into sase. It uses Rust-backed SQLite/query/mutation logic
through the required `sase_core_rs` extension, with JSONL export for git portability (inspired by
[Fossil](https://fossil-scm.org/)). Issues are organized into plan-like containers and executable child phases. Plan
beads can represent ordinary plans, executable epics, or legend-level roadmaps through their `tier` metadata.

![Bead issue model, storage sync, and epic wave execution](images/bead-epic-work-infographic.png)

## Table of Contents

- [Quick Start](#quick-start)
- [Data Model](#data-model)
  - [Issue Types](#issue-types)
  - [Status Lifecycle](#status-lifecycle)
  - [Dependencies](#dependencies)
- [Storage](#storage)
  - [Directory Structure](#directory-structure)
  - [SQLite + JSONL Dual Storage](#sqlite-jsonl-dual-storage)
  - [Sync Mechanism](#sync-mechanism)
- [CLI Commands](#cli-commands)
- [Rust Backend](#rust-backend)
- [Current Checkout Source Of Truth](#current-checkout-source-of-truth)
- [ACE TUI Integration](#ace-tui-integration)

## Quick Start

```bash
sase bead init                                          # Initialize beads in current project
sase bead create -t "New feature" --type "plan(sdd/tales/202605/feature.md)" --tier plan
sase bead create -t "Epic" --type "plan(sdd/epics/202605/epic.md)" --tier epic
sase bead create -t "Roadmap" --type "plan(sdd/legends/202605/roadmap.md)" --tier legend --epic-count 3
sase bead create -t "Linked epic" --type "plan(sdd/epics/202605/epic.md,<legend-id>)" --tier epic
sase bead create -t "Sub-task" --type "phase(beads-001)"   # Create a phase under a plan
sase bead list                                          # List open and in-progress issues
sase bead list --status=open                            # List open issues
sase bead list --status=closed                          # List closed issues
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
sase bead work beads-001                                # Launch agents for an epic or legend plan bead
```

## Data Model

### Issue Types

| Type      | Description                              | ID Format            |
| --------- | ---------------------------------------- | -------------------- |
| **Plan**  | Plan-like container with a tier          | `{prefix}-{counter}` |
| **Phase** | Executable task within an epic/plan bead | `{parent_id}.{N}`    |

Plans are groupings that can optionally link to an SDD file via the `design` field. Phases always belong to a parent
plan and use hierarchical IDs (e.g., `beads-001.1`, `beads-001.2`).

Plan beads carry a tier. The SDD paths below are the conventional version-controlled locations; in local SDD mode the
same artifact classes live under `.sase/sdd/`.

| Tier     | SDD Path                    | Behavior                                                                      |
| -------- | --------------------------- | ----------------------------------------------------------------------------- |
| `plan`   | `sdd/tales/{YYYYMM}/*.md`   | Normal non-epic implementation plan                                           |
| `epic`   | `sdd/epics/{YYYYMM}/*.md`   | Executable multi-phase plan accepted by `sase bead work`                      |
| `legend` | `sdd/legends/{YYYYMM}/*.md` | Higher-level coordination plan; launches epic-planning agents by `epic_count` |

Linked epics use the existing parented plan syntax:

```bash
sase bead create --title "Epic" --type "plan(sdd/epics/202605/epic.md,<legend_bead_id>)" --tier epic
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

When version-controlled mode is enabled (`sdd.version_controlled` config):

```
sdd/beads/
  beads.db              # SQLite database (gitignored)
  issues.jsonl          # Git-tracked JSONL export
  config.json           # Configuration (issue prefix, counter, owner)
```

In non-version-controlled mode, the directory is `.sase/sdd/beads/` with the same structure.

Normal bead commands read and write one store for the active checkout. In version-controlled mode, that source of truth
is the current checkout's `sdd/beads/issues.jsonl` plus `sdd/beads/config.json`. Legacy stores are migration-only
concerns; they are not merged into normal `sase bead` reads.

### SQLite + JSONL Dual Storage

Rust owns the bead storage/query/mutation path. SQLite is the local query cache and mutation target; JSONL is the
git-portable format that can be committed. The two are kept in sync:

- **Writes** run through Rust mutation transactions, update SQLite, then export the portable JSONL state.
- **Reads** run through Rust read APIs, rebuilding SQLite from JSONL first when the cache is missing or stale.
- **Fresh clones** rebuild the SQLite database automatically from `issues.jsonl` on first access.

The `.gitignore` excludes `beads.db*` files so only `issues.jsonl` and `config.json` are tracked in git.

### Sync Mechanism

`sase bead sync` exports the current bead state to `issues.jsonl` and stages that file in git. The JSONL file contains
one JSON object per line, sorted by issue ID for clean diffs.

On project open, if the JSONL file is newer than the database (or the database is missing), the database is
automatically rebuilt from JSONL. This handles fresh clones and manual JSONL edits transparently.

## CLI Commands

### `sase bead init`

Initialize the bead store for the current project. In version-controlled SDD mode this is `sdd/beads/`; in local SDD
mode this is `.sase/sdd/beads/`.

### `sase bead create`

Create a new issue.

| Flag                | Required | Description                                                                                                                                                                                                                                 |
| ------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-t, --title`       | yes      | Issue title                                                                                                                                                                                                                                 |
| `-T, --type`        | yes      | Bead type: `plan(<file>)`, `plan(<file>,<parent>)`, or `phase(<parent_id>)`                                                                                                                                                                 |
| `-d, --description` | no       | Issue description                                                                                                                                                                                                                           |
| `-a, --assignee`    | no       | Assignee name                                                                                                                                                                                                                               |
| `--tier`            | no       | Plan-bead tier: `plan`, `epic`, or `legend`                                                                                                                                                                                                 |
| `-c, --changespec`  | no       | Attach a ChangeSpec name to a plan bead                                                                                                                                                                                                     |
| `-b, --bug-id`      | no       | Bug ID for the attached ChangeSpec; requires `--changespec`                                                                                                                                                                                 |
| `-E, --epic-count`  | no       | Positive number of epics proposed by a legend plan bead                                                                                                                                                                                     |
| `-m, --model`       | no       | Model used when this bead is launched. Provider-qualified (e.g. `codex/gpt-5.5`) or a configured local alias (e.g. `#pro`). On epic and legend plan beads this becomes the land-agent model; on phase beads it is the per-phase work model. |

ChangeSpec metadata is valid only on plan beads. It is used by the epic-approval and `sase bead work` flows to keep plan
beads linked to the ChangeSpec they are intended to produce.

### `sase bead list`

List issues with optional filtering. Without `--status`, the command lists `open` and `in_progress` issues; pass
`--status=closed` when you need closed history. `--status`, `--type`, and `--tier` are repeatable.

| Flag           | Values                          | Description                   |
| -------------- | ------------------------------- | ----------------------------- |
| `-s, --status` | `open`, `in_progress`, `closed` | Filter by status (repeatable) |
| `-t, --type`   | `plan`, `phase`                 | Filter by type (repeatable)   |
| `--tier`       | `plan`, `epic`, `legend`        | Filter by plan-bead tier      |

### `sase bead show <id>`

Display complete details for an issue including status, type, tier, epic count, parent/children, dependencies, blockers,
description, notes, ChangeSpec metadata, model, and linked plan path.

### `sase bead ready`

Show issues that are ready to work on: `open` status with all dependencies `closed`.

### `sase bead open <id>`

Reopen an issue by setting its status to `open`. This is equivalent to `sase bead update <id> --status=open`.

### `sase bead update <id>`

Update one or more fields on an issue.

| Flag                | Description                                             |
| ------------------- | ------------------------------------------------------- |
| `-s, --status`      | Change status                                           |
| `-t, --title`       | Change title                                            |
| `-d, --description` | Change description                                      |
| `-n, --notes`       | Change notes                                            |
| `-D, --design`      | Change plan path                                        |
| `-a, --assignee`    | Change assignee                                         |
| `--tier`            | Change plan tier                                        |
| `-E, --epic-count`  | Change legend epic count                                |
| `-m, --model`       | Change the launch model. Pass an empty string to clear. |

### `sase bead close <id> [<id2> ...]`

Close one or more issues.

Closing a plan bead also closes its phase children. Use this intentionally: phase agents should close only their
assigned phase bead, not the parent epic.

| Flag           | Description                |
| -------------- | -------------------------- |
| `-r, --reason` | Optional close reason text |

### `sase bead rm <id>`

Remove an issue and cascade-delete all its children. This is irreversible.

### `sase bead dep add <issue> <depends_on>`

Add a dependency: `<issue>` depends on `<depends_on>`. The issue becomes blocked if the dependency is not yet closed.

### `sase bead blocked`

Show all issues that have at least one active (non-closed) blocker.

### `sase bead sync`

Export the current bead state to `issues.jsonl` and stage that file in git. It does not create a commit; the staged
JSONL is included in the next normal project or SDD commit.

| Flag           | Description                              |
| -------------- | ---------------------------------------- |
| `-s, --status` | Check whether JSONL has unstaged changes |

### `sase bead stats`

Show project statistics: total, open, in-progress, and closed counts, plus plan and phase counts.

### `sase bead doctor`

Run health checks on the beads database. Checks for:

- Missing `config.json`, `issues.jsonl`, or `beads.db`
- Uncommitted JSONL changes
- Orphan children (phases whose parent plan is missing)

If bead commands fail before opening a store, run `sase core health` first. It verifies that the required `sase_core_rs`
extension is importable and exposes the representative bead CLI binding used by the fast path.

### `sase bead onboard`

Display a quick-start guide with common command examples.

### `sase bead work <id>`

Run an entire epic-tier plan end-to-end by launching one agent per phase plus a final land agent, or run a legend-tier
plan by launching one epic-planning agent per stored `epic_count`.

For epic-tier plans, the command:

1. Validates that `<epic_id>` resolves to an issue of type `plan` with `tier=epic`. If the plan is already marked
   `is_ready_to_work`, the command treats the run as a retry and schedules any remaining non-closed phases.
2. Scans the live agent registry for any visible agent already named `<epic_id>.<N>` (for any open phase), `<epic_id>`
   (for the land agent), or the legacy `<epic_id>.land` land-agent name, and refuses to launch when a collision exists,
   listing the offending artifact directories so the user can wipe/delete or otherwise resolve the orphan first.
   (`--dry-run` downgrades this to a warning and continues.)
3. Flips the epic plan bead's `is_ready_to_work` flag to `True` when it was not already ready.
4. Builds a Kahn-wave schedule from the epic's open phase children, respecting dependencies.
5. Pre-claims each phase bead — sets `status=in_progress` and `assignee=<phase_bead_id>` (i.e. `<epic_id>.<N>`).
6. Hands a single `---`-separated multi-prompt to the agent launcher. Each per-phase agent is spawned with name
   `<epic_id>.<N>` and references the [`work_phase_bead`](xprompt.md#available-tags) xprompt; a final land agent named
   `<epic_id>` references the [`land_epic`](xprompt.md#available-tags) xprompt. Phase dependencies become `%w` waits on
   blocker phase-agent names, and the land agent waits on every launched phase agent. Because `%w` requires a successful
   `done.json` outcome, a failed or killed phase keeps dependent phases and the land agent parked until the phase name
   is retried successfully. If a phase or land bead has a stored `model`, the corresponding segment also emits a
   `%model:<value>` directive so that agent runs under the requested model. Each segment uses the force-reuse
   `%name:!<agent_name>` form so re-running `sase bead work` after a killed or failed run wipes the stale name owners
   before the relaunch — the command is safe to retry.

For legend-tier plans, the command:

1. Validates that `<id>` resolves to a plan bead with `tier=legend`, a positive `epic_count`, and a linked legend plan
   path.
2. Scans the live agent registry for generated epic-planning agent names like `<legend_id>.1.0` and refuses collisions.
3. Flips the legend plan bead's `is_ready_to_work` flag to `True` when launching.
4. Hands a single `---`-separated multi-prompt to the agent launcher. Each epic-planning segment is named
   `%name:!<legend_id>.<N>.0` and includes `%epic`; epic-planning segments do **not** carry `%approve`, because their
   generated plans go through the normal plan-approval flow. Epic `N > 1` also waits on `%w:<legend_id>.<N-1>`, so epic
   planning proceeds in order. After the epic-planning segments, a final land-legend segment named `<legend_id>`
   references the [`land_legend`](xprompt.md#available-tags) xprompt, waits on the last epic-planning agent, and carries
   `%approve` so it can self-approve. When the legend bead has a stored `model`, that segment also emits
   `%model:<value>`. As with the epic-tier rendering, every segment uses the force-reuse `%name:!<agent_name>` form so
   the command is safe to retry after a killed or failed run.

Legend work does not create phase beads directly. The spawned epic-planning agents create epic plans, and the existing
`bd/new_epic` automation handles the linked epic and phase beads after those plans are approved.

| Flag            | Description                                                                       |
| --------------- | --------------------------------------------------------------------------------- |
| `-n, --dry-run` | Print the wave plan and rendered multi-prompt without mutating state or launching |
| `-y, --yes`     | Skip the launch confirmation prompt                                               |

The work xprompts are resolved by `XPromptTag` (tag-based lookup), so a project-local or user-defined xprompt with the
matching tag overrides the built-in. For epic-tier work, every phase and land segment carries a `%approve` directive so
spawned agents can self-approve their own plans without a human-in-the-loop checkpoint between waves. For legend-tier
work, only the trailing land-legend segment carries `%approve`; each epic-planning segment uses `%epic` and pauses for
the normal plan-approval flow before its child phases run.

When the epic plan bead is attached to ChangeSpec metadata (`--changespec` / `--bug-id`), `sase bead work` preserves the
current project's VCS context in the generated prompt. The first phase segment targets the project reference and adds a
`#pr` reference for the ChangeSpec, while later phase and land segments target the ChangeSpec ref directly. For
non-ChangeSpec epics launched from a known SASE workspace, each segment is still prefixed with the detected VCS workflow
and project name (for example `#git:sase` or `#gh:sase-org/sase`). If the current directory is not associated with a
SASE project, the prompts are left unprefixed and run in the caller's normal launch context.

If launching the multi-prompt fails partway through, the launcher SIGTERMs any already-spawned children before rolling
back the pre-claims and the `is_ready_to_work` flag when this run set it (best-effort), so the epic can be retried
without leaving zombie agents behind.

After the agents launch successfully, `sase bead work` commits the resulting `sdd/beads/issues.jsonl` mutation when the
beads directory belongs to a git repository and the JSONL file changed. This commit records the bead launch state only;
it does not commit any code produced later by the spawned agents. Epic launches use the subject
`chore: mark bead work launched for <id>`; legend launches use `chore: mark legend work launched for <id>`. If the git
commit fails, the command reports that agents were already launched and exits non-zero so the operator can commit or
repair the bead state explicitly. Dry runs and stores outside git do not create a commit.

When that commit succeeds and `bead.push_after_commit` is `true` (the default), `sase bead work` follows it with
`git push` so the launched-work record reaches the remote without a manual follow-up step. The push inherits the
caller's stdin/stdout/stderr, so interactive credential prompts still work. If the repository has no remote configured,
the push is skipped silently — the local commit stands on its own. If `git push` fails (for example because the remote
rejected the update), the failure is reported as a warning only: the bead-launch commit is preserved on the local branch
and the warning text includes the manual `git push` invocation to retry.

Set `bead.push_after_commit: false` in `~/.config/sase/sase.yml` to disable the auto-push — useful for local-only
checkouts, or when you would rather batch the bead-launch commit with later commits before pushing.

## Rust Backend

The bead data model, JSONL/config codecs, SQLite rebuild/query layer, mutation transactions, ID allocation,
deterministic work-plan DAG, and common CLI output planning are implemented in `sase-core` and exposed through
`sase_core_rs`. Python keeps the host logic that belongs in the application layer: locating the active bead store,
relativizing plan paths, resolving VCS context and xprompts for `sase bead work`, prompting the user, launching agents,
rolling back failed launches, and incrementing telemetry counters.

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

In version-controlled mode, every `sase bead` read and mutation command uses the current checkout's
`sdd/beads/issues.jsonl` and `sdd/beads/config.json`. Running the command in `myproject/` reads that checkout's bead
state; running it in `myproject_2/` reads `myproject_2/sdd/beads/`. The CLI does not merge sibling workspace stores, and
duplicate IDs in another checkout do not override the active checkout's records.

ID allocation also uses only the active store's `config.json` and `issues.jsonl`. If a sibling checkout has not pulled
or merged the latest bead state, it may allocate IDs based on its local state; sync bead changes through the normal VCS
workflow when several agents are coordinating on the same project.

Cross-project helper surfaces, such as mobile/editor bead pickers, may inspect one canonical store per known project,
but they still do not merge numbered sibling workspaces or legacy bead stores for the same project.

## ACE TUI Integration

### Plan File Linking

When creating a plan bead with `--type plan(PATH)`, the file path is stored in the `design` field. The ACE TUI can
navigate from a bead to its linked SDD file.

For SDD-generated epics, `PATH` should be the shared plan reference emitted by the plan approval flow:
`sdd/epics/YYYYMM/*.md` when `sdd.version_controlled: true`, or `.sase/sdd/epics/YYYYMM/*.md` in local SDD mode. These
relative references stay portable across checkouts while each checkout reads its own bead store.

### Plan Approval Flow

The plan approval popup in ACE includes normal approval, **E** (Epic), and **L** (Legend) actions. Normal approval saves
to `sdd/tales/`, Epic saves to `sdd/epics/` and launches the epic follow-up that creates an `epic`-tier plan bead plus
phase beads, and Legend saves to `sdd/legends/` and launches a legend follow-up that records a `legend`-tier plan bead
with `epic_count` before starting the legend work chain.
