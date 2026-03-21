# Research: `sase-beads` -- Replacing Beads with a Standalone Package

## Motivation

The external `beads` (bd) tool is a 37MB Go binary with 80+ fields per issue, 14 database tables, Dolt-backed versioned
SQL, a daemon process, federation, compaction, molecules, gates, wisps, and more. We use roughly 5% of it. A standalone
`sase-beads` Python package exposing an `sbd` CLI can give us just the essentials: simple issue tracking for agent
workflows, stored in a git-friendly format, with no external binary dependencies.

### Package Design

- **Repo**: `sase-beads` (separate git repo, e.g. `sase-org/sase-beads`)
- **Package name**: `sase-beads` (PyPI) / `sase_beads` (importable)
- **Entry point**: `sbd` CLI command (replaces `bd`)
- **Dependency**: `sase` adds `sase-beads` as a dependency in `pyproject.toml`
- **Why separate**: Keeps issue tracking decoupled from the agent toolkit. Other projects could use `sbd` independently.

---

## What We Actually Use from Beads

### Commands (keep these)

| Command                     | Purpose                                |
| --------------------------- | -------------------------------------- |
| `sbd ready`                 | Show open issues with no blockers      |
| `sbd list`                  | List issues with status/type filters   |
| `sbd create`                | Create issue with title, type          |
| `sbd show <id>`             | Show issue details + dependencies      |
| `sbd close <id> [<id2>...]` | Close one or more issues               |
| `sbd update <id>`           | Update status, title, description, etc |
| `sbd dep add <a> <b>`       | Add dependency (a depends on b)        |
| `sbd blocked`               | Show blocked issues                    |
| `sbd sync`                  | Sync with git remote                   |
| `sbd stats`                 | Project statistics                     |
| `sbd doctor`                | Health check                           |

### Issue Types

Only two issue types:

| Type      | Description                                                                     |
| --------- | ------------------------------------------------------------------------------- |
| **epic**  | Top-level work unit. Groups related children. Can be blocked by other epics.    |
| **child** | A task within an epic. Automatically has a parent-child dependency to its epic. |

Epics are the primary unit of planning. Children are the work items within an epic. Every child belongs to exactly one
epic (enforced by a required `parent_id` foreign key).

### Fields (keep these)

| Field          | Type     | Notes                                      |
| -------------- | -------- | ------------------------------------------ |
| `id`           | str      | e.g. "sase-03v" -- prefix + base36 counter |
| `title`        | str      | Required                                   |
| `status`       | enum     | open, in_progress, closed                  |
| `issue_type`   | enum     | epic, child                                |
| `parent_id`    | str      | Required for children, null for epics      |
| `owner`        | str      | Git email                                  |
| `assignee`     | str      | Who's working on it                        |
| `created_at`   | datetime | ISO 8601                                   |
| `created_by`   | str      | Creator name                               |
| `updated_at`   | datetime | Last update                                |
| `closed_at`    | datetime | When closed                                |
| `close_reason` | str      | Why closed                                 |
| `description`  | str      | Detailed description                       |
| `notes`        | str      | Additional notes                           |
| `design`       | str      | Path to plan/spec doc                      |
| `dependencies` | list     | `[{issue_id, depends_on_id, created_at}]`  |

**Removed from beads**: `priority` (not needed -- ordering is implicit via creation order and epic grouping).

### What We Drop

Everything else: Dolt backend, daemon, federation, molecules, gates, wisps, compaction, agent state tracking,
interactions table, priority levels, task/bug/feature types, 60+ unused fields, Go binary dependency.

---

## Current Integration Points (in sase)

These files touch beads and would need updating during migration:

| File                                                       | Integration                                                                    |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `tools/sase_bd`                                            | Bash wrapper -- workspace routing, JSONL fallback, auto-commit to `.sase/sdd/` |
| `src/sase/sdd.py`                                          | `init_beads()`, `check_epic_available()` -- subprocess calls to `bd`           |
| `src/sase/main/entry.py`                                   | `init-beads` CLI command                                                       |
| `src/sase/axe_run_agent_exec.py`                           | `check_epic_available()` call                                                  |
| `src/sase/ace/tui/modals/plan_approval_modal.py`           | `beads_supported` flag                                                         |
| `src/sase/ace/tui/actions/agents/_notification_actions.py` | Passes `beads_supported`                                                       |
| `tools/pyvision-260225`                                    | `bd show` for epic symbol validation                                           |
| `Justfile`                                                 | Sets `BD_COMMAND=tools/sase_bd`                                                |
| `src/sase/default_config.yml`                              | `bd/next`, `bd/new_epic`, `bd/land_epic` xprompts                              |
| `.beads/`                                                  | Config, metadata, JSONL data                                                   |

---

## Storage Design: SQLite with JSONL Export

### Recommended: SQLite primary + JSONL git-tracked export

This is the Fossil pattern: SQLite is the local query engine, JSONL is the git-portable format.

```
.sbd/
  sbd.db          # SQLite database (gitignored)
  issues.jsonl    # Git-tracked export (one JSON object per line)
  config.yaml     # Optional config (issue prefix, etc.)
```

**Why SQLite for local storage:**

- Rich queries (SQL), indexes, joins -- find blocked issues with a single recursive CTE
- Schema enforcement via migrations
- Single file, zero-config, no daemon
- Python stdlib: `import sqlite3` -- no dependencies
- Excellent for the read-heavy, single-writer workload of issue tracking

**Why JSONL for git transport:**

- Append-only diffs are clean in git
- Concurrent appends to different lines auto-merge
- Single-line JSON is independently parseable (fault-tolerant)
- Human-readable without tooling
- Already proven by beads' own JSONL export

**Workflow:**

1. On `sbd` first run: if `issues.jsonl` exists but `sbd.db` doesn't, import JSONL into SQLite
2. All reads/writes go through SQLite
3. On mutations, auto-export to JSONL (or on explicit `sbd sync`)
4. JSONL is committed to git; SQLite is gitignored
5. On `git pull`, if JSONL is newer than SQLite, re-import (upsert semantics)

### SQLite Schema (minimal)

```sql
CREATE TABLE issues (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open'
                  CHECK(status IN ('open', 'in_progress', 'closed')),
    issue_type  TEXT NOT NULL DEFAULT 'child'
                  CHECK(issue_type IN ('epic', 'child')),
    parent_id   TEXT
                  REFERENCES issues(id) ON DELETE CASCADE,
    owner       TEXT,
    assignee    TEXT,
    created_at  TEXT NOT NULL,  -- ISO 8601
    created_by  TEXT,
    updated_at  TEXT NOT NULL,
    closed_at   TEXT,
    close_reason TEXT,
    description TEXT,
    notes       TEXT,
    design      TEXT,
    -- Enforce: children must have a parent, epics must not
    CHECK(
        (issue_type = 'child' AND parent_id IS NOT NULL) OR
        (issue_type = 'epic' AND parent_id IS NULL)
    )
);

CREATE TABLE dependencies (
    issue_id       TEXT NOT NULL,
    depends_on_id  TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    created_by     TEXT,
    PRIMARY KEY (issue_id, depends_on_id),
    FOREIGN KEY (issue_id) REFERENCES issues(id) ON DELETE CASCADE,
    FOREIGN KEY (depends_on_id) REFERENCES issues(id) ON DELETE CASCADE
);

CREATE INDEX idx_issues_status ON issues(status);
CREATE INDEX idx_issues_type ON issues(issue_type);
CREATE INDEX idx_issues_parent ON issues(parent_id);
CREATE INDEX idx_deps_depends_on ON dependencies(depends_on_id);
```

**Ready query** (open issues with no active blockers):

```sql
SELECT i.* FROM issues i
WHERE i.status = 'open'
  AND i.id NOT IN (
    SELECT d.issue_id FROM dependencies d
    JOIN issues blocker ON d.depends_on_id = blocker.id
    WHERE blocker.status IN ('open', 'in_progress')
  )
ORDER BY i.created_at ASC;
```

**Epic children query** (all children of an epic):

```sql
SELECT * FROM issues WHERE parent_id = ? ORDER BY created_at ASC;
```

**Epic completion check** (are all children closed?):

```sql
SELECT COUNT(*) = 0 FROM issues
WHERE parent_id = ? AND status != 'closed';
```

---

## Prior Art Survey

### Tools That Store Issues in Git

| Tool                | Language | Storage                                    | Status       | Key Insight                                                    |
| ------------------- | -------- | ------------------------------------------ | ------------ | -------------------------------------------------------------- |
| **git-bug**         | Go       | Git objects under `refs/bugs/*`            | Active       | Operation-log model for conflict-free merges                   |
| **git-issue**       | Shell    | Text files on orphan branch                | Active       | One dir per issue, one file per field -- maximally transparent |
| **git-appraise**    | Go       | Single-line JSON in git notes              | Semi-dormant | `cat_sort_uniq` merge = never conflicts                        |
| **SIT**             | Rust     | Reduction files (event sourcing)           | Semi-active  | Works with any file sync, not just git                         |
| **Fossil**          | C        | SQLite (as cache over immutable artifacts) | Active       | DB is derived, artifacts are canonical                         |
| **driusan/bug**     | Go       | Plain text dirs in working tree            | Semi-active  | Filesystem IS the query interface                              |
| **ripissue**        | Rust     | Filesystem dirs                            | Active       | Tight branch-per-issue integration                             |
| **Bugs Everywhere** | Python   | `.be/` directory, XML-like files           | Dormant      | Multi-VCS was too ambitious                                    |
| **TicGit**          | Ruby     | Files on separate branch                   | Abandoned    | Pioneered separate-branch pattern                              |
| **Ditz**            | Ruby     | YAML files                                 | Abandoned    | YAML is human-editable but fragile                             |
| **git-dit**         | Rust     | Git commit messages                        | Dormant      | No merge conflicts, but no queryability                        |

### Key Patterns Worth Adopting

1. **Fossil's "canonical artifacts + derived cache" pattern.** This is exactly what "JSONL primary + SQLite cache" gives
   us. The JSONL travels through git (canonical), the SQLite is rebuilt locally (derived). If the SQLite file is ever
   corrupted or missing, rebuild from JSONL.

2. **git-appraise's single-line JSON.** One JSON object per line in JSONL means concurrent appends from different
   branches produce clean 3-way merges. No special merge drivers needed.

3. **git-bug's operation-log model.** Rather than storing final state, store operations (create, update, close).
   Replaying operations computes current state. This is the most robust approach for concurrent edits, but adds
   complexity. For our use case (single writer per workspace), final-state JSONL is sufficient.

4. **git-issue's transparency.** The data format should be understandable without tooling. JSONL with clear field names
   achieves this.

---

## JSONL Format

Each line is a self-contained JSON object representing the current state of one issue:

```jsonl
{"id":"sase-001","title":"Implement sbd CLI","status":"open","issue_type":"epic","parent_id":null,"owner":"user@example.com","created_at":"2026-03-16T10:00:00Z","created_by":"User","updated_at":"2026-03-16T10:00:00Z","dependencies":[]}
{"id":"sase-002","title":"Add ready command","status":"open","issue_type":"child","parent_id":"sase-001","owner":"user@example.com","created_at":"2026-03-16T10:05:00Z","created_by":"User","updated_at":"2026-03-16T10:05:00Z","dependencies":[]}
{"id":"sase-003","title":"Add list command","status":"open","issue_type":"child","parent_id":"sase-001","owner":"user@example.com","created_at":"2026-03-16T10:10:00Z","created_by":"User","updated_at":"2026-03-16T10:10:00Z","dependencies":[{"issue_id":"sase-003","depends_on_id":"sase-002"}]}
```

**Export strategy:** Full snapshot -- rewrite the entire file on each export. This keeps the file compact and
human-scannable. Since issues are one-per-line and sorted by ID, git diffs remain clean (changed lines show as
modifications, new issues as additions).

**Alternative considered:** Append-only operation log. More merge-friendly but harder to read and requires replay logic.
Not worth the complexity for our scale (hundreds, not millions of issues).

---

## Package Structure (`sase-beads` repo)

```
sase-beads/
  pyproject.toml          # hatchling build, sbd entry point
  src/
    sase_beads/
      __init__.py
      cli.py              # sbd CLI (click or argparse)
      db.py               # SQLite schema, migrations, queries
      jsonl.py            # JSONL import/export
      model.py            # Issue dataclass (epic, child)
      ids.py              # ID generation (prefix + base36)
      sync.py             # Git sync logic
      config.py           # Project config (.sbd/config.yaml)
  tests/
    ...
```

**Entry point in `pyproject.toml`:**

```toml
[project.scripts]
sbd = "sase_beads.cli:main"
```

**Python API** (for sase to import directly instead of subprocess):

```python
from sase_beads import SbdProject

project = SbdProject("/path/to/repo")
epic = project.create(title="New feature", issue_type="epic")
child = project.create(title="Subtask", issue_type="child", parent_id=epic.id)
ready = project.ready()  # List[Issue]
project.close(child.id)
project.sync()
```

---

## Implementation Plan

### Phase 1: `sase-beads` package -- Core data layer

- New repo `sase-beads` with hatchling build
- SQLite schema + migrations in `src/sase_beads/db.py`
- JSONL import/export in `src/sase_beads/jsonl.py`
- Issue model (dataclass with epic/child types) in `src/sase_beads/model.py`
- ID generation (prefix + base36 counter) in `src/sase_beads/ids.py`
- Epic-child relationship enforcement (parent_id required for children)

### Phase 2: `sbd` CLI commands

Register `sbd` as the entry point:

```
sbd create --title="..." --type=epic
sbd create --title="..." --type=child --parent=<epic-id>
sbd list [--status=open] [--type=epic]
sbd show <id>
sbd ready
sbd update <id> --status=in_progress
sbd close <id> [<id2>...]
sbd dep add <issue> <depends-on>
sbd blocked
sbd sync
sbd stats
sbd doctor
```

### Phase 3: Integrate into sase

- Add `sase-beads` as a dependency in sase's `pyproject.toml`
- Update `tools/sase_bd` wrapper to call `sbd` instead of `bd`
- Update `src/sase/sdd.py` to use `sase_beads` Python API directly (no subprocess)
- Update TUI integration points
- Update xprompts and agent instructions (AGENTS.md, CLAUDE.md, PRIME.md)

### Phase 4: Migration & Cleanup

- Write a one-time migration script: reads `.beads/issues.jsonl`, maps old types (task/bug/feature → child), imports
  into `.sbd/`
- Remove `bd` binary dependency
- Remove `.beads/` directory (after migration verified)
- Update all documentation

---

## Open Questions

1. **ID format:** Keep the current `sase-xxx` base36 format? Or switch to something else (sequential integers, ULIDs)?
   The base36 format is compact and familiar from beads.

2. **Workspace routing:** The current `tools/sase_bd` wrapper routes ephemeral workspaces (sase_100, sase_101) to the
   primary workspace's `.beads/`. Should `sbd` handle this internally via config, or keep a thin bash wrapper?

3. **SDD integration:** Currently `.beads/` can live inside `.sase/sdd/` for non-version-controlled repos. Keep this
   pattern with `.sbd/` or simplify?

4. **Git sync strategy:** Auto-commit JSONL on every mutation (current behavior via `tools/sase_bd`)? Or only on
   explicit `sbd sync`?

5. **Type migration:** When importing from beads, should task/bug/feature all become `child` under a catch-all epic? Or
   create separate epics per old type?
