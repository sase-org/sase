---
keywords: [bead, epic, phase, dependency, claim, beads create, beads ready, beads close]
---

# Bead System

## Model

A bead (Issue) has: `id`, `title`, `status`, `issue_type`, `parent_id`, `owner`, `assignee`, `dependencies`,
`created_at`, `created_by`, `updated_at`, `closed_at`, `close_reason`, `description`, `notes`, `design`.

**Statuses:** OPEN, IN_PROGRESS, CLOSED.

**Types:** PLAN (epic-level, can be top-level, has optional `design` file path) and PHASE (work item, must have a
`parent_id` — enforced by DB constraint).

**ID generation:** Top-level IDs use a counter-based scheme (e.g., `beads-03v` in base36). Child IDs are hierarchical:
`<parent_id>.<N>` where N increments per parent.

## Dependency Semantics

`A depends on B` means B must be CLOSED before A is considered ready. Both OPEN and IN_PROGRESS statuses on B block A.
Cross-epic dependencies are allowed — a PHASE in Plan A can depend on a PHASE in Plan B.

## Ready vs In-Progress

**Ready** = OPEN + no non-CLOSED blockers. The `beads ready` command returns only issues matching this criteria.

**IN_PROGRESS never appears in the ready list** — this is enforced by the SQL query (`i.status = 'open'`), acting as a
soft claim mechanism. Setting a bead to IN_PROGRESS removes it from the ready pool without formal assignment logic.

## Closing Behavior

Closing a **PLAN** cascades to all non-CLOSED children (PHASE issues), applying the same `close_reason` to each.

## Persistence

- **JSONL** (`issues.jsonl`) is the source of truth for git
- **SQLite DB** is rebuilt from JSONL whenever JSONL's mtime is newer than the DB's
- Every mutation exports to JSONL immediately via `_export()`

## Workspace Merging

Sibling workspace directories (`<basename>_<N>`) are scanned and their beads databases merged. For each issue ID, the
version with the most recent `updated_at` timestamp wins.

## Key CLI Commands

| Command                                     | Purpose                            |
| ------------------------------------------- | ---------------------------------- |
| `sase bead create -t "title" -T plan(file)` | Create a PLAN with optional design |
| `sase bead create -t "title" -T phase(id)`  | Create a PHASE under a PLAN        |
| `sase bead ready`                           | List ready (unblocked OPEN) issues |
| `sase bead dep add <issue> <depends-on>`    | Add a dependency                   |
| `sase bead close <id> [-r reason]`          | Close issue (cascades for PLANs)   |
| `sase bead sync [-s]`                       | Sync across workspaces             |
| `sase bead list [-s status] [-t type]`      | List/filter issues                 |
| `sase bead show <id>`                       | Show issue details                 |
| `sase bead blocked`                         | Show blocked issues                |
| `sase bead rm <id>`                         | Remove issue and children          |
