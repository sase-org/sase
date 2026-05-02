---
create_time: 2026-03-28 17:29:01
status: done
prompt: sdd/prompts/202603/yyyymm_sdd_dirs.md
---

# Plan: Organize Plans and Specs into YYYYMM Subdirectories

## Problem

All plan and spec files are stored flat in `plans/` and `specs/` directories. With 156+ plans and 123+ specs, these
directories are getting unwieldy. We want to organize them into `plans/<YYYYMM>/` and `specs/<YYYYMM>/` subdirectories
based on the creation month.

## Design Decisions

### YYYYMM Source

For **new** files: derive YYYYMM from `datetime.now()` in the configured timezone (same timezone used by
`add_create_time_frontmatter`).

For **existing** files being moved at commit time (the `_handle_sase_plan` copy path): extract YYYYMM from the plan
file's `create_time` frontmatter field if present, otherwise fall back to current time.

### Lookup Helper

Add a `find_sdd_file(base_dir, kind, name)` helper to `sase/sdd/files.py` that searches for `{kind}/{name}` first (exact
path), then `{kind}/*/{name}` (YYYYMM subdirs), returning the first match. This makes lookups backward-compatible with
existing flat files.

### Xprompt Template References

The `bd/review/plan` and `bd/review/prompt` xprompts use `@specs/{{ file_base }}.md` and `@plans/{{ file_base }}.md`.
These need to use the new `find_sdd_file` approach. Since these are agent prompts with `@file` references, the simplest
fix is to use glob-style references: `@specs/**/{{ file_base }}.md` and `@plans/**/{{ file_base }}.md`. This way the `@`
file reference resolver will find files in any YYYYMM subdirectory.

### bd/land_epic Instructions

Update the `bd/land_epic` xprompt text to say "plans/ directory (in a YYYYMM subdirectory)" instead of just "plans/
directory".

## Changes

### Phase 1: Core helper — `sase/sdd/files.py`

1. Add `get_yyyymm() -> str` helper that returns current YYYYMM string using `sase.core.time.get_timezone()`.
2. Add `find_sdd_file(base_dir: Path, kind: str, name: str) -> Path | None` that searches for a file first at
   `base_dir/{kind}/{name}`, then via `base_dir/{kind}/*/{name}` glob.
3. Update `write_sdd_files()` to write into `specs/<YYYYMM>/` and `plans/<YYYYMM>/` subdirectories.

### Phase 2: Agent exec plan — `sase/axe/run_agent_exec_plan.py`

4. Update `_commit_sdd_files()` to use `find_sdd_file` to locate spec/plan files (supports both flat and YYYYMM paths).
5. Update `plan_ref` construction (lines 319-325) to use the actual path from `write_sdd_files` instead of hardcoding
   `plans/{name}.md`.
6. Update `SASE_PLAN` env var setting (line 339) similarly.

### Phase 3: Commit workflow — `sase/workflows/commit/workflow.py`

7. Update `_handle_sase_plan()` copy destination to use YYYYMM subdirectory (derived from plan file's `create_time`
   frontmatter or current time).

### Phase 4: Default config xprompts — `sase/default_config.yml`

8. Update `bd/review/plan` template: `@specs/{{ file_base }}.md` → `@specs/**/{{ file_base }}.md` (and same for plans).
9. Update `bd/review/prompt` template similarly.
10. Update `bd/land_epic` instructions to mention YYYYMM subdirectory structure.

### Phase 5: TUI notification modal — `sase/ace/tui/actions/agents/_notification_modals.py`

11. Update the `.sase/plans/` save path to include YYYYMM subdirectory.

### Phase 6: Tests

12. Update `test_write_sdd_files`, `test_write_sdd_files_missing_plan`, `test_write_sdd_files_creates_dirs` to expect
    YYYYMM subdirectory structure.
13. Update `_commit_sdd_files` tests to use YYYYMM directory structure for test fixtures.
14. Update `TestHandleSasePlan` tests to expect YYYYMM subdirectory in destination paths.
15. Add tests for `find_sdd_file` (flat path, YYYYMM path, missing file).
16. Add test for `get_yyyymm`.

### Phase 7: Move existing files

17. Move existing flat `plans/*.md` and `specs/*.md` files into appropriate YYYYMM subdirectories based on their
    `create_time` frontmatter (or git blame date as fallback).
