---
bead_id: sase-5fkw
prompt: sdd/prompts/202603/sase_beads_migration.md
---

# Plan: sase-beads Package + Migration from steveyegge/beads

## Overview

Build the `sase-beads` Python package in the `../sase-beads` repo (currently empty), then migrate sase from the external
`bd` Go binary to `sbd`. The package provides simple epic/child issue tracking backed by SQLite + JSONL, with zero
external dependencies beyond Python stdlib.

**Reference**: `sdd/research/202603/sase_beads.md` contains the full design (schema, JSONL format, field definitions, etc.).

---

## Phase 1: sase-beads Core Library

**Repo**: `../sase-beads` **Goal**: Scaffold the repo and implement the core data layer with thorough tests.

### 1.1 Repo scaffold

- `pyproject.toml` — hatchling build, Python >=3.12, zero runtime dependencies
  - Match conventions from sase and sase-github repos (ruff, mypy, pytest, coverage config)
  - Entry point: `sbd = "sase_beads.cli:main"` (CLI implemented in Phase 2)
  - Dev deps: ruff, mypy, pytest, pytest-cov
- `Justfile` — install, lint, fmt, test, check targets (same pattern as sase)
- `src/sase_beads/__init__.py` — package root, export `SbdProject` (implemented Phase 2)
- `.gitignore` — standard Python + `.sbd/sbd.db`
- `LICENSE` — MIT

### 1.2 Models (`src/sase_beads/model.py`)

- `Issue` dataclass with fields from research doc: id, title, status, issue_type, parent_id, owner, assignee,
  created_at, created_by, updated_at, closed_at, close_reason, description, notes, design
- `Dependency` dataclass: issue_id, depends_on_id, created_at, created_by
- Status enum: `open`, `in_progress`, `closed`
- IssueType enum: `epic`, `child`
- Validation: children must have parent_id, epics must not

### 1.3 ID generation (`src/sase_beads/ids.py`)

- Prefix + base36 counter format (e.g., `sase-03v`)
- Read current counter from `.sbd/config.yaml`
- Thread-safe increment

### 1.4 Database layer (`src/sase_beads/db.py`)

- SQLite schema from research doc (issues + dependencies tables, indexes, CHECK constraints)
- Schema creation/migration on first connect
- Query functions: create_issue, get_issue, list_issues, update_issue, close_issue, ready_issues, blocked_issues,
  add_dependency, get_dependencies, get_epic_children, stats
- All queries parameterized (no SQL injection)

### 1.5 JSONL layer (`src/sase_beads/jsonl.py`)

- `export_to_jsonl(db, path)` — full snapshot, sorted by ID, one JSON object per line
- `import_from_jsonl(path, db)` — upsert semantics, rebuild SQLite from JSONL
- Handle missing/empty JSONL gracefully
- Dependencies embedded in each issue's JSON (as in research doc format)

### 1.6 Tests

- `tests/test_model.py` — validation (child requires parent, epic rejects parent)
- `tests/test_ids.py` — counter increment, base36 encoding, prefix handling
- `tests/test_db.py` — CRUD operations, ready query, blocked query, epic children, cascading close, CHECK constraints
- `tests/test_jsonl.py` — round-trip export/import, empty file, corrupt line handling

### Verification

```bash
just check  # fmt-check + lint + test all pass
```

---

## Phase 2: sbd CLI + Python API

**Repo**: `../sase-beads` **Prereq**: Phase 1 complete (core library with passing tests) **Goal**: Implement all CLI
commands and the `SbdProject` public API.

### 2.1 Project class (`src/sase_beads/project.py`)

- `SbdProject` class — main public API
  - `__init__(root_dir)` — locate/create `.sbd/` directory, init SQLite from JSONL if needed
  - `init()` — create `.sbd/` with config.yaml, empty db
  - `create(title, issue_type, parent_id=None, ...)` → Issue
  - `show(issue_id)` → Issue (with dependencies)
  - `list(status=None, issue_type=None)` → list[Issue]
  - `ready()` → list[Issue] (open, no active blockers)
  - `update(issue_id, **fields)` → Issue
  - `close(issue_ids, reason=None)` → list[Issue]
  - `add_dependency(issue_id, depends_on_id)`
  - `blocked()` → list[Issue]
  - `sync()` — export to JSONL, git add + commit
  - `stats()` → dict (counts by status, type)
  - `doctor()` → list[str] (diagnostic messages)
- Auto-export to JSONL on every mutation (create, update, close, dep add)
- Export `SbdProject` from `__init__.py`

### 2.2 Config (`src/sase_beads/config.py`)

- `.sbd/config.yaml`: issue prefix (default: repo name), next counter value, owner (git email)
- Load/save with PyYAML... actually, no external deps. Use a simple YAML-subset parser or just JSON.
  - Decision: use `json` for config (`.sbd/config.json`) to avoid PyYAML dependency. Keep it simple.
  - Actually, re-read the research doc — it says `config.yaml`. Let's use a minimal key-value parser that handles the
    simple YAML we need (flat key: value pairs). No nested structures needed.

### 2.3 CLI (`src/sase_beads/cli.py`)

- Use `argparse` (stdlib, no click dependency)
- Subcommands matching research doc:
  - `sbd init` — create `.sbd/` in current directory
  - `sbd create --title="..." --type=epic|child [--parent=<id>]`
  - `sbd list [--status=open|in_progress|closed] [--type=epic|child]`
  - `sbd show <id>`
  - `sbd ready`
  - `sbd update <id> [--status=...] [--title=...] [--description=...] [--notes=...] [--design=...] [--assignee=...]`
  - `sbd close <id> [<id2>...] [--reason="..."]`
  - `sbd dep add <issue> <depends-on>`
  - `sbd blocked`
  - `sbd sync [--status]`
  - `sbd stats`
  - `sbd doctor`
  - `sbd onboard` — print quick-start guide (matches bd onboard behavior)
- Output formatting: human-readable tables/lists for terminal, structured for piping
- Exit codes: 0 success, 1 error

### 2.4 Git sync (`src/sase_beads/sync.py`)

- `git_sync()` — git add `.sbd/issues.jsonl` + commit with message
- `sync_status()` — check if JSONL has uncommitted changes
- `rebuild_from_jsonl()` — if JSONL is newer than db, reimport
- Use `subprocess.run` for git commands (no gitpython dependency)

### 2.5 Tests

- `tests/test_project.py` — SbdProject API: create/show/list/ready/update/close/dep/blocked/stats
- `tests/test_cli.py` — CLI invocation via subprocess or `argparse` parsing, test each subcommand
- `tests/test_sync.py` — git sync in a temp git repo, JSONL commit verification
- `tests/test_config.py` — config load/save, default values

### Verification

```bash
just check                    # All checks pass
sbd init && sbd create --title="Test" --type=epic && sbd list  # Manual smoke test
```

---

## Phase 3: Documentation + Integration Tests

**Repo**: `../sase-beads` **Prereq**: Phase 2 complete (working CLI + API) **Goal**: Write comprehensive README, add
integration tests, polish the package.

### 3.1 README.md

Write a thorough README covering:

- **Overview** — what sase-beads is, why it exists (lightweight git-native issue tracking)
- **Installation** — `pip install sase-beads` / `pip install -e ".[dev]"`
- **Quick Start** — init, create epic, create children, list, close workflow
- **CLI Reference** — all commands with examples and option descriptions
- **Python API Reference** — `SbdProject` class with code examples
- **Storage Format** — explain SQLite + JSONL dual storage, `.sbd/` directory structure
- **Data Model** — epic/child types, status lifecycle, dependencies
- **Development** — setup, running tests, linting, contributing

### 3.2 Integration tests

- `tests/test_integration.py` — end-to-end workflows:
  - Full epic lifecycle: init → create epic → create children → update status → close children → close epic
  - Dependency chains: create chain, verify blocked/ready queries
  - JSONL round-trip: create issues, export, delete db, reimport, verify identical state
  - Concurrent workspace: two SbdProject instances on same `.sbd/` (verify no corruption)
  - Git sync: init git repo, create issues, sync, verify commit, pull fresh clone, rebuild from JSONL
  - Edge cases: empty project, closing already-closed issue, invalid parent_id, missing `.sbd/`

### 3.3 Package polish

- `CLAUDE.md` for the sase-beads repo (build commands, architecture overview)
- `py.typed` marker file for PEP 561 type checking
- Review all public API type annotations
- Ensure `--cov-fail-under` is set appropriately (aim for 90%+)

### Verification

```bash
just check   # All checks pass including new integration tests
```

---

## Phase 4: sase Migration

**Repos**: `../sase_100` (sase) + `../sase-beads` **Prereq**: Phase 3 complete (sase-beads package is
published/installable) **Goal**: Migrate sase from steveyegge/beads (`bd`) to sase-beads (`sbd`).

### 4.1 Add dependency

- Add `sase-beads` to sase's `pyproject.toml` dependencies
- Run `just install` to verify resolution

### 4.2 Update `src/sase/sdd.py`

- Replace `init_beads()` to use `SbdProject.init()` (Python API, no subprocess)
- Replace `check_epic_available()` to check for `.sbd/` directory instead of `.beads/`
- Rename functions: `init_beads` → `init_sbd`, `check_epic_available` → `check_sbd_available`

### 4.3 Update `src/sase/main/entry.py`

- Rename `init-beads` command to `init-sbd` (or keep both with deprecation warning)
- Update to call new `init_sbd()` function

### 4.4 Update `src/sase/axe_run_agent_exec.py`

- Update `check_epic_available()` call to `check_sbd_available()`
- Fix the key naming mismatch bug: `epic_available` vs `beads_supported` (both should use the same key)

### 4.5 Update TUI components

- `src/sase/ace/tui/modals/plan_approval_modal.py` — rename `beads_supported` → `sbd_available` (or similar)
- `src/sase/ace/tui/actions/agents/_notification_actions.py` — match the key name
- `src/sase/notifications/senders.py` — fix `action_data` key to match what TUI reads

### 4.6 Update xprompts (`src/sase/default_config.yml`)

- `bd/next` → `sbd/next` — update to use `sbd` commands
- `bd/new_epic` → `sbd/new_epic` — update to use `sbd create --type=epic`
- `bd/land_epic` → `sbd/land_epic` — update to use `sbd close`
- Update `bd/review/*` xprompts

### 4.7 Update `tools/sase_bd`

- Replace with a thin `tools/sase_sbd` wrapper that:
  - Routes ephemeral workspaces (sase_100, sase_101) to primary workspace
  - Calls `sbd` instead of `bd`
  - Handles SDD directory routing
  - Auto-commits JSONL changes to `.sase/sdd/` git repo
- Keep it simpler than the current wrapper (no JSONL fallback needed since sbd IS the JSONL tool)

### 4.8 Update `Justfile`

- Replace `BD_COMMAND=tools/sase_bd` with `SBD_COMMAND=tools/sase_sbd` (or equivalent)

### 4.9 Migration script

- One-time script to convert `.beads/` → `.sbd/`:
  - Read `.beads/issues.jsonl`
  - Map old types (task, bug, feature) → `child` under a migration epic
  - Map old priorities → drop (not supported)
  - Preserve IDs, timestamps, dependencies
  - Write to `.sbd/issues.jsonl` + rebuild SQLite
- Can be a standalone script in `tools/` or an `sbd migrate-from-beads` command

### 4.10 Update documentation

- `AGENTS.md` — replace all `bd`/`beads`/`sase_bd` references with `sbd`/`sase_sbd`
- `CLAUDE.md` — update references
- Agent instructions in system prompts — update command examples

### 4.11 Cleanup

- Remove `tools/sase_bd` (replaced by `tools/sase_sbd`)
- Remove any `.beads/` directory references from `.gitignore`
- Add `.sbd/sbd.db` to `.gitignore` (SQLite cache is not tracked)
- Remove `bd` binary from PATH requirements

### Verification

```bash
# In sase repo:
just install && just check

# Smoke test the full workflow:
.venv/bin/sase init-sbd
tools/sase_sbd create --title="Test epic" --type=epic
tools/sase_sbd ready
tools/sase_sbd list
```

---

## Open Decisions (for implementer)

1. **Config format**: Research doc says `config.yaml` but package has zero deps. Options: minimal YAML parser for flat
   key-value, or use JSON (`config.json`). Recommend JSON for simplicity.

2. **Workspace routing**: Keep as bash wrapper (`tools/sase_sbd`) or build into `sbd` CLI via a `--dir` flag? Recommend
   keeping the wrapper for now — it's simple and proven.

3. **ID prefix**: Default to repo directory name? Or require explicit config? Recommend: auto-detect from git remote or
   directory name, overridable in config.

4. **`init-beads` deprecation**: Keep the old command with a deprecation warning pointing to `init-sbd`? Or just rename?
   Recommend: just rename, since we control all callers.

## Notes

- sase-beads has **zero runtime dependencies** (only stdlib: sqlite3, json, subprocess, dataclasses, argparse, pathlib)
- The `sase-beads` repo follows the same conventions as sase and sase-github (hatchling, ruff, mypy, pytest)
- Each phase is self-contained and can be verified independently with `just check`
