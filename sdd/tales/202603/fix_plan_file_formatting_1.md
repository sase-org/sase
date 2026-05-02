---
create_time: 2026-03-30 14:08:24
status: done
---

# Fix: Plan files not formatted with prettier before being committed

## Problem

When an agent creates a plan file (`sase_plan_*.md`) and submits it via `sase plan`, the file is never formatted with
prettier. This causes downstream issues:

1. **The original plan file persists in the workspace root unformatted.** After the planner is killed and the coder
   agent is spawned, the original `sase_plan_*.md` sits in the workspace root. When the coder runs `just check`,
   prettier fails on the unformatted markdown. The coder wastes time diagnosing and formatting a file it didn't create.

2. **The archived copy in `~/.sase/plans/` is also unformatted.** `save_plan_to_sase()` uses `shutil.copy2()` — a raw
   byte copy. If the commit workflow later copies from the archive to `plans/YYYYMM/` (because the SDD path file was
   cleaned by `#gh` pre-step), `_handle_sase_plan()` also uses `shutil.copy2()` without formatting.

Note: `write_sdd_files()` in `sdd/files.py` already calls `format_with_prettier()` — the SDD path is fine. The gap is
that the **original file** and the **archive** are never formatted, and the commit workflow's copy path also lacks
formatting.

## Flow Trace

1. Agent writes `sase_plan_foo.md` in workspace root (unformatted)
2. Agent calls `sase plan sase_plan_foo.md`
3. `plan_command_handler.py` → `save_plan_to_sase()` → raw copy to `~/.sase/plans/foo.md`
4. Pending marker written, planner killed via SIGTERM
5. Plan approved, `handle_plan_marker()` runs:
   - `write_sdd_files()` formats and writes to `plans/YYYYMM/foo.md` (OK)
   - Sets `SASE_PLAN` to the formatted path
6. Coder agent spawned — original `sase_plan_foo.md` still in root, unformatted (PROBLEM)
7. Coder runs `just check` → prettier fails on root plan file (PROBLEM)
8. During commit, `_handle_sase_plan()` may copy from unformatted archive if SDD file is missing (PROBLEM)

## Fix

### Phase 1: Format in `plan_command_handler.py` (primary fix)

**File**: `src/sase/main/plan_command_handler.py`

After validating the plan file exists but before archiving, format the file **in-place** with prettier. This ensures:

- The original file in the workspace root is formatted (won't cause prettier failures for the coder)
- The archived copy is also formatted (since `save_plan_to_sase` copies the now-formatted file)
- `write_sdd_files()` later calling `format_with_prettier()` is a no-op (idempotent)

### Phase 2: Format in `_handle_sase_plan()` (safety net)

**File**: `src/sase/workflows/commit/workflow.py`

After the `shutil.copy2()` copy in `_handle_sase_plan()` (line 253), format the copied plan file with prettier. This
handles edge cases where the archive wasn't formatted (e.g., plans created before Phase 1 is deployed).

## Scope

1. `src/sase/main/plan_command_handler.py` — format plan file in-place before archiving
2. `src/sase/workflows/commit/workflow.py` — format plan after copy in `_handle_sase_plan()`
