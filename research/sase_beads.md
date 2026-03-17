# Research: `sase bd` -- Replacing Beads with a Built-in Solution

## Motivation

The external `beads` (bd) tool is a 37MB Go binary with 80+ fields per issue, 14 database tables, Dolt-backed versioned
SQL, a daemon process, federation, compaction, molecules, gates, wisps, and more. We use roughly 5% of it. A built-in
`sase bd` subcommand can give us just the essentials: simple issue tracking for agent workflows, stored in a
git-friendly format, with no external dependencies.

---

## What We Actually Use from Beads

### Commands (keep these)

| Command                    | Purpose                                                      |
| -------------------------- | ------------------------------------------------------------ |
| `bd ready`                 | Show open issues with no blockers (respecting `defer_until`) |
| `bd list`                  | List issues with status/type/priority filters                |
| `bd create`                | Create issue with title, type, priority, description         |
| `bd show <id>`             | Show issue details + dependencies                            |
| `bd close <id> [<id2>...]` | Close one or more issues                                     |
| `bd update <id>`           | Update status, title, description, notes, design, assignee   |
| `bd dep add <a> <b>`       | Add dependency (a depends on b)                              |
| `bd blocked`               | Show blocked issues                                          |
| `bd sync`                  | Sync with git remote                                         |
| `bd stats`                 | Project statistics                                           |
| `bd doctor`                | Health check                                                 |

### Fields (keep these)

| Field          | Type     | Notes                                           |
| -------------- | -------- | ----------------------------------------------- |
| `id`           | str      | e.g. "sase-03v" -- prefix + base36 counter      |
| `title`        | str      | Required                                        |
| `status`       | enum     | open, in_progress, closed                       |
| `priority`     | int      | 0-4 (0=critical, 4=backlog)                     |
| `issue_type`   | enum     | task, bug, feature, epic                        |
| `owner`        | str      | Git email                                       |
| `assignee`     | str      | Who's working on it                             |
| `created_at`   | datetime | ISO 8601                                        |
| `created_by`   | str      | Creator name                                    |
| `updated_at`   | datetime | Last update                                     |
| `closed_at`    | datetime | When closed                                     |
| `close_reason` | str      | Why closed                                      |
| `description`  | str      | Detailed description                            |
| `notes`        | str      | Additional notes                                |
| `design`       | str      | Path to plan/spec doc                           |
| `dependencies` | list     | `[{issue_id, depends_on_id, type, created_at}]` |

### What We Drop

Everything else: Dolt backend, daemon, federation, molecules, gates, wisps, compaction, agent state tracking,
interactions table, 60+ unused fields, Go binary dependency.

---

## Current Integration Points

These are the files that touch beads and would need updating:

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
.sase/bd/
  bd.db           # SQLite database (gitignored)
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

1. On `sase bd` first run: if `issues.jsonl` exists but `bd.db` doesn't, import JSONL into SQLite
2. All reads/writes go through SQLite
3. On mutations, auto-export to JSONL (or on explicit `sase bd sync`)
4. JSONL is committed to git; SQLite is gitignored
5. On `git pull`, if JSONL is newer than SQLite, re-import (upsert semantics)

### SQLite Schema (minimal)

```sql
CREATE TABLE issues (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open'
                  CHECK(status IN ('open', 'in_progress', 'closed')),
    priority    INTEGER NOT NULL DEFAULT 2
                  CHECK(priority BETWEEN 0 AND 4),
    issue_type  TEXT NOT NULL DEFAULT 'task'
                  CHECK(issue_type IN ('task', 'bug', 'feature', 'epic')),
    owner       TEXT,
    assignee    TEXT,
    created_at  TEXT NOT NULL,  -- ISO 8601
    created_by  TEXT,
    updated_at  TEXT NOT NULL,
    closed_at   TEXT,
    close_reason TEXT,
    description TEXT,
    notes       TEXT,
    design      TEXT
);

CREATE TABLE dependencies (
    issue_id       TEXT NOT NULL,
    depends_on_id  TEXT NOT NULL,
    dep_type       TEXT NOT NULL DEFAULT 'blocks'
                     CHECK(dep_type IN ('blocks', 'parent-child')),
    created_at     TEXT NOT NULL,
    created_by     TEXT,
    PRIMARY KEY (issue_id, depends_on_id),
    FOREIGN KEY (issue_id) REFERENCES issues(id) ON DELETE CASCADE,
    FOREIGN KEY (depends_on_id) REFERENCES issues(id) ON DELETE CASCADE
);

CREATE INDEX idx_issues_status ON issues(status);
CREATE INDEX idx_issues_priority ON issues(priority);
CREATE INDEX idx_issues_type ON issues(issue_type);
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
      AND d.dep_type = 'blocks'
  )
ORDER BY i.priority ASC, i.created_at ASC;
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
{"id":"sase-001","title":"Add ready command","status":"open","priority":2,"issue_type":"task","owner":"user@example.com","created_at":"2026-03-16T10:00:00Z","created_by":"User","updated_at":"2026-03-16T10:00:00Z","dependencies":[]}
{"id":"sase-002","title":"Fix blocked query","status":"closed","priority":1,"issue_type":"bug","owner":"user@example.com","created_at":"2026-03-16T10:05:00Z","created_by":"User","updated_at":"2026-03-16T11:00:00Z","closed_at":"2026-03-16T11:00:00Z","close_reason":"Fixed in abc123","dependencies":[{"issue_id":"sase-002","depends_on_id":"sase-001","type":"blocks"}]}
```

**Export strategy:** Full snapshot -- rewrite the entire file on each export. This keeps the file compact and
human-scannable. Since issues are one-per-line and sorted by ID, git diffs remain clean (changed lines show as
modifications, new issues as additions).

**Alternative considered:** Append-only operation log. More merge-friendly but harder to read and requires replay logic.
Not worth the complexity for our scale (hundreds, not millions of issues).

---

## Implementation Plan

### Phase 1: Core data layer

- SQLite schema + migrations in `src/sase/bd/db.py`
- JSONL import/export in `src/sase/bd/jsonl.py`
- Issue model (dataclass) in `src/sase/bd/model.py`
- ID generation (prefix + base36 counter) in `src/sase/bd/ids.py`

### Phase 2: CLI commands

Register `sase bd` as a subcommand group:

```
sase bd create --title="..." --type=task --priority=2
sase bd list [--status=open] [--type=bug]
sase bd show <id>
sase bd ready
sase bd update <id> --status=in_progress
sase bd close <id> [<id2>...]
sase bd dep add <issue> <depends-on>
sase bd blocked
sase bd sync
sase bd stats
sase bd doctor
```

### Phase 3: Migration

- Write a one-time migration script that reads `.beads/issues.jsonl` and imports into the new format
- Update `tools/sase_bd` wrapper to call `sase bd` instead of `bd`
- Update `src/sase/sdd.py` to use Python API instead of subprocess
- Update TUI integration points
- Update xprompts and agent instructions

### Phase 4: Cleanup

- Remove `bd` binary dependency
- Remove `.beads/` directory (after migration)
- Update AGENTS.md, CLAUDE.md, PRIME.md

---

## Open Questions

1. **ID format:** Keep the current `sase-xxx` base36 format? Or switch to something else (sequential integers, ULIDs)?

2. **Workspace routing:** The current `tools/sase_bd` wrapper routes ephemeral workspaces (sase_100, sase_101) to the
   primary workspace's `.beads/`. Should `sase bd` handle this internally in Python, or keep the bash wrapper?

3. **SDD integration:** Currently `.beads/` can live inside `.sase/sdd/` for non-version-controlled repos. Keep this
   pattern or simplify?

4. **Git sync strategy:** Auto-commit JSONL on every mutation (current behavior via `tools/sase_bd`)? Or only on
   explicit `sase bd sync`?

5. **Interactions/audit:** Beads has an `interactions.jsonl` for agent audit trails. Do we want anything similar, or
   drop it entirely?
