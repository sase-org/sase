# Bead Issue Tracking

Bead is a lightweight, git-native issue tracking system built into sase. It uses SQLite for local querying with JSONL
export for git portability (inspired by [Fossil](https://fossil-scm.org/)). Issues are organized into a two-tier
hierarchy: **Plans** (epics) group related work, and **Phases** (child tasks) break plans into actionable steps.

## Table of Contents

- [Quick Start](#quick-start)
- [Data Model](#data-model)
  - [Issue Types](#issue-types)
  - [Status Lifecycle](#status-lifecycle)
  - [Dependencies](#dependencies)
- [Storage](#storage)
  - [Directory Structure](#directory-structure)
  - [SQLite + JSONL Dual Storage](#sqlite--jsonl-dual-storage)
  - [Sync Mechanism](#sync-mechanism)
- [CLI Commands](#cli-commands)
- [Multi-Workspace Support](#multi-workspace-support)
- [ACE TUI Integration](#ace-tui-integration)

## Quick Start

```bash
sase bead init                                          # Initialize beads in current project
sase bead create --title="New feature" --plan=plan.md   # Create a plan linked to a plan file
sase bead create --title="Sub-task" --parent=beads-001  # Create a phase under a plan
sase bead list                                          # List all issues
sase bead list --status=open                            # List open issues
sase bead ready                                         # Show issues ready to work on
sase bead show beads-001                                # View issue details
sase bead update beads-001.1 --status=in_progress       # Claim an issue
sase bead close beads-001.1                             # Close an issue
sase bead dep add beads-001.2 beads-001.1               # Add dependency
sase bead blocked                                       # Show blocked issues
sase bead sync                                          # Commit JSONL to git
sase bead stats                                         # Project statistics
sase bead doctor                                        # Health check
```

## Data Model

### Issue Types

| Type      | Description                          | ID Format            |
| --------- | ------------------------------------ | -------------------- |
| **Plan**  | Top-level work unit (epic)           | `{prefix}-{counter}` |
| **Phase** | Task within a plan (requires parent) | `{parent_id}.{N}`    |

Plans are top-level groupings that can optionally link to a plan/spec file via the `design` field. Phases always belong
to a parent plan and use hierarchical IDs (e.g., `beads-001.1`, `beads-001.2`).

### Status Lifecycle

| Status        | Icon | Description               |
| ------------- | ---- | ------------------------- |
| `open`        | `○`  | Not started               |
| `in_progress` | `◐`  | Currently being worked on |
| `closed`      | `✓`  | Completed or abandoned    |

Status can transition freely between any values via `sase bead update --status=<status>`.

### Dependencies

Dependencies are one-way relationships: issue A **depends on** issue B. An issue is:

- **Ready** if it is `open` and all its dependencies are `closed`.
- **Blocked** if it has at least one dependency with status `open` or `in_progress`.

## Storage

### Directory Structure

When version-controlled mode is enabled (`sdd.version_controlled` config):

```
.sase_beads/
  beads.db              # SQLite database (gitignored)
  issues.jsonl          # Git-tracked JSONL export
  config.json           # Configuration (issue prefix, counter, owner)
```

In non-version-controlled mode, the directory is `.sase/sdd/beads/` with the same structure.

### SQLite + JSONL Dual Storage

SQLite is the primary store for fast local queries. JSONL is the git-portable format that gets committed. The two are
kept in sync:

- **Writes** go to SQLite first, then export to JSONL on sync.
- **Reads** come from SQLite for speed.
- **Fresh clones** rebuild the SQLite database automatically from `issues.jsonl` on first access.

The `.gitignore` excludes `beads.db*` files so only `issues.jsonl` and `config.json` are tracked in git.

### Sync Mechanism

`sase bead sync` exports the current SQLite state to `issues.jsonl` and commits it to git. The JSONL file contains one
JSON object per line, sorted by issue ID for clean diffs.

On project open, if the JSONL file is newer than the database (or the database is missing), the database is
automatically rebuilt from JSONL. This handles fresh clones and manual JSONL edits transparently.

## CLI Commands

### `sase bead init`

Initialize the beads directory in the current project.

### `sase bead create`

Create a new issue.

| Flag            | Required | Description                                      |
| --------------- | -------- | ------------------------------------------------ |
| `--title`       | yes      | Issue title                                      |
| `--plan`        | no       | Path to plan file (creates a plan bead)          |
| `--parent`      | no       | Parent bead ID (creates a phase under this plan) |
| `--description` | no       | Issue description                                |
| `--assignee`    | no       | Assignee name                                    |

Type is determined automatically: providing `--plan` creates a plan; providing `--parent` creates a phase.

### `sase bead list`

List issues with optional filtering. Closed beads are excluded from the default output.

| Flag           | Values                          | Description                   |
| -------------- | ------------------------------- | ----------------------------- |
| `-s, --status` | `open`, `in_progress`, `closed` | Filter by status (repeatable) |
| `-t, --type`   | `plan`, `phase`                 | Filter by type (repeatable)   |

### `sase bead show <id>`

Display complete details for an issue including status, type, parent/children, dependencies, blockers, description,
notes, and linked plan path.

### `sase bead ready`

Show issues that are ready to work on: `open` status with all dependencies `closed`.

### `sase bead update <id>`

Update one or more fields on an issue.

| Flag                | Description        |
| ------------------- | ------------------ |
| `-s, --status`      | Change status      |
| `-t, --title`       | Change title       |
| `-d, --description` | Change description |
| `-n, --notes`       | Change notes       |
| `-D, --design`      | Change plan path   |
| `-a, --assignee`    | Change assignee    |

### `sase bead close <id> [<id2> ...]`

Close one or more issues.

| Flag       | Description                |
| ---------- | -------------------------- |
| `--reason` | Optional close reason text |

### `sase bead rm <id>`

Remove an issue and cascade-delete all its children. This is irreversible.

### `sase bead dep add <issue> <depends_on>`

Add a dependency: `<issue>` depends on `<depends_on>`. The issue becomes blocked if the dependency is not yet closed.

### `sase bead blocked`

Show all issues that have at least one active (non-closed) blocker.

### `sase bead sync`

Export the SQLite database to JSONL and commit to git.

| Flag       | Description                          |
| ---------- | ------------------------------------ |
| `--status` | Check sync status without committing |

### `sase bead stats`

Show project statistics: total, open, in-progress, and closed counts, plus plan and phase counts.

### `sase bead doctor`

Run health checks on the beads database. Checks for:

- Missing `config.json`, `issues.jsonl`, or `beads.db`
- Uncommitted JSONL changes
- Orphan children (phases whose parent plan is missing)

### `sase bead onboard`

Display a quick-start guide with common command examples.

## Multi-Workspace Support

When running in version-controlled mode with multiple workspace variants (e.g., `myproject/`, `myproject_2/`,
`myproject_3/`), bead provides a merged read view across all workspaces:

- **Reads** (list, show, ready, blocked, stats) aggregate issues from all workspace variants using an in-memory SQLite
  merge. For duplicate IDs across workspaces, the version with the most recent `updated_at` wins.
- **Writes** (create, update, close, rm, dep add) always go to the primary workspace only.

This enables multiple agents working in different workspace clones to track their own issues while still providing a
unified view of all work.

## ACE TUI Integration

### Plan File Linking

When creating a plan bead with `--plan PATH`, the file path is stored in the `design` field. The ACE TUI can navigate
from a bead to its linked plan file.

### Epic Approval Flow

The plan approval popup in ACE shows an **E** (Epic) option when `.sase_beads/` exists and version-controlled mode is
enabled. Pressing E creates the plan file, launches an epic agent, and creates beads for each phase defined in the plan.
