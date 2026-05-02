---
bead_id: sase-cu8
prompt: sdd/prompts/202603/migrate_beads_to_core.md
---

# Plan: Migrate sase-beads into sase core

## Overview

Migrate the standalone `sase-beads` package into `sase` core as `src/sase/bead/`, replacing the `sbd` CLI with
`sase bead`, updating storage paths, removing the `tools/sase_sbd` wrapper, and updating all chezmoi references.

## Key Design Decisions

- **Module location**: `src/sase/bead/` (matching the new `sase bead` command name)
- **Storage when `sdd.version_controlled` is set**: `sdd/beads/` at project root (git-tracked)
- **Storage when `sdd.version_controlled` is NOT set**: `.sase/sdd/beads/` (auto-initialized on first use, no
  `sase init-beads` command needed)
- **The internal directory name changes from `.sbd/` to `beads/`** within both paths (i.e., `sdd/beads/` or
  `.sase/sdd/beads/`)
- **CLI**: `sase bead <subcommand>` replaces `sbd <subcommand>` and `tools/sase_sbd <subcommand>`
- **Auto-init**: When `sdd.version_controlled` is NOT set, the `.sase/sdd/beads/` directory is auto-initialized on first
  `sase bead` command (replacing `sase init-sbd`)

## Phase 1: Copy sase-beads source into `src/sase/bead/`

Copy the 8 source modules from `../sase-beads/src/sase_beads/` into `src/sase/bead/`, adjusting imports from
`sase_beads.X` to `sase.bead.X`:

- `__init__.py` — re-export `BeadProject` (rename from `SbdProject`)
- `model.py` — `Issue`, `Dependency`, `Status`, `IssueType` (unchanged)
- `db.py` — SQLite CRUD layer (unchanged)
- `ids.py` — Base36 ID generation (unchanged)
- `jsonl.py` — JSONL import/export (unchanged)
- `config.py` — Config management; change `.sbd/` references to `beads/` directory naming
- `sync.py` — Git sync; update file paths
- `project.py` — Rename `SbdProject` → `BeadProject`; change `.sbd/` → internal naming

Also copy tests from `../sase-beads/tests/` into `tests/test_bead/` and update imports.

**Files created/modified:**

- Create `src/sase/bead/__init__.py`
- Create `src/sase/bead/model.py`
- Create `src/sase/bead/db.py`
- Create `src/sase/bead/ids.py`
- Create `src/sase/bead/jsonl.py`
- Create `src/sase/bead/config.py`
- Create `src/sase/bead/sync.py`
- Create `src/sase/bead/project.py`
- Create `src/sase/bead/py.typed`
- Create `tests/test_bead/` with migrated tests
- Update `pyproject.toml` to remove `sase-beads` dependency if present

## Phase 2: Add `sase bead` CLI subcommand

Port the CLI from `sase_beads/cli.py` into `src/sase/bead/cli.py` and wire it into sase's main parser/entry point as a
`bead` subcommand with nested subcommands.

**Changes:**

- Create `src/sase/bead/cli.py` — Port all 13 subcommand handlers, using `sase.bead.project.BeadProject`
- Edit `src/sase/main/parser.py` — Add `bead` subcommand with nested subparsers (replacing `init-sbd`)
- Edit `src/sase/main/entry.py` — Add `bead` command handler that dispatches to `sase.bead.cli`, remove `init-sbd`
  handler

The CLI must handle **auto-initialization**: when `sdd.version_controlled` is NOT set, `sase bead` auto-creates
`.sase/sdd/beads/` (with git init inside `.sase/sdd/` if needed) before running the subcommand. This replaces the old
`sase init-sbd` / `sbd init` flow.

When `sdd.version_controlled` IS set, `sase bead` operates on `sdd/beads/` at the project root.

**Auto-commit behavior** (previously in `tools/sase_sbd`): After write operations (`create`, `update`, `close`, `dep`,
`init`) when operating in the non-VC `.sase/sdd/` path, auto-commit to the `.sase/sdd/` git repo.

## Phase 3: Update `sdd.py` and internal references

Update all sase-internal code that references `sbd`, `.sbd/`, `sase_beads`, or `tools/sase_sbd`.

**Files to modify:**

- `src/sase/sdd.py` — Update `init_sbd()` → use `sase.bead.project.BeadProject`, change `.sbd/` → `beads/`, update
  `check_sbd_available()` to check new paths (`sdd/beads/` for VC, `.sase/sdd/beads/` for non-VC)
- `src/sase/axe_run_agent_exec.py` — Update references from `sbd` to `bead`, update xprompt references
- `src/sase/ace/tui/modals/plan_approval_modal.py` — Rename `sbd_available` → `bead_available` (or keep, less critical)
- `src/sase/llm_provider/_plan_utils.py` — Same rename
- `src/sase/notifications/senders.py` — Same rename
- `src/sase/default_config.yml` — Update xprompt workflows (`sbd/next`, `sbd/new_epic`, `sbd/land_epic`, `sbd/review/*`)
  to use `sase bead` instead of `tools/sase_sbd`; rename xprompt keys from `sbd/` to `bead/`
- `tests/test_sdd.py` — Update tests for new paths and function signatures
- `tests/test_epic_approval.py` — Update tests
- `AGENTS.md` — Update issue tracking section to reference `sase bead` instead of `tools/sase_sbd`
- `tools/AGENTS.md` — Remove `sase_sbd` section

**Files to delete:**

- `tools/sase_sbd` — No longer needed (functionality is now in `sase bead` CLI)
- `tools/sase_bd` — Legacy wrapper, no longer needed
- `tools/migrate_beads_to_sbd` — Migration complete

## Phase 4: Update chezmoi repo references

Update all chezmoi-managed files that reference `sbd`, `tools/sase_sbd`, or `.sbd/`.

**Files to modify in `~/.local/share/chezmoi/`:**

1. **`home/bin/executable_ccommit`** (critical):
   - Update `resolve_sbd_command()` → use `.venv/bin/sase bead` instead of `sbd`
   - Update `do_sbd_close()` → call `.venv/bin/sase bead close` instead of `sbd close`
   - Update `do_sbd_sync()` → check for `sdd/beads/` dir instead of `.sbd/`, call `.venv/bin/sase bead sync`
   - Add auto-commit for `sdd/beads/` directory changes (stage + commit any modified files in `sdd/beads/` after
     push)

2. **`home/bin/executable_next_bead`**:
   - Update `sbd ready` → `.venv/bin/sase bead ready`
   - Update `sbd update` → `.venv/bin/sase bead update`
   - Update `sbd show` → `.venv/bin/sase bead show`

3. **`home/dot_claude/settings.json`**:
   - Update `PreCompact` and `SessionStart` hooks: replace `sase_sbd prime` / `sbd prime` with
     `.venv/bin/sase bead prime` (or equivalent)

4. **`home/dot_claude/commands/sbd/`** — Rename directory to `home/dot_claude/commands/bd/` or `bead/` and update
   contents:
   - `next.md` → Replace `tools/sase_sbd` with `.venv/bin/sase bead`
   - `new_epic.md` → Same
   - `land_epic.md` → Same

5. **`home/dot_claude/skills/commit/SKILL.md`**:
   - Update `sbd list --status=in_progress` → `.venv/bin/sase bead list --status=in_progress`
   - Update bead association instructions

6. **Commit all chezmoi changes** using the commit skill (NOT `git commit`)

## Phase 5: Verification and cleanup

- Run `just install && just check` to verify all lint/type/test checks pass
- Verify `sase bead` CLI works end-to-end (init, create, list, show, ready, update, close, sync)
- Verify ccommit bead integration works
- Remove `sase-beads` from any dependency lists in `pyproject.toml`
- Clean up any remaining references to `sbd` or `.sbd/` in the codebase
