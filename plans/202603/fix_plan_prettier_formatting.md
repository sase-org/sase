---
create_time: 2026-03-29 18:02:35
status: done
---

# Fix: Plan files not formatted by prettier before commit

## Problem

PRs created via the `#pr` xprompt are failing the `fmt-md-check` GitHub Actions job because plan files committed to
`plans/YYYYMM/` are not formatted with prettier.

## Root Cause

In `CommitWorkflow.run()` (`src/sase/workflows/commit/workflow.py:88-97`), the order of operations is:

1. `_run_precommit(cwd)` — runs `just fix`, which includes `fmt-md` (prettier on `**/*.md`)
2. `_handle_beads(cwd)` — bead lifecycle management
3. `_handle_sase_plan(cwd)` — copies plan file into `plans/YYYYMM/` directory

The plan file is copied into the repo **after** the precommit command has already run prettier. So prettier never sees
the plan file, and it gets committed unformatted.

## Fix

Move `_handle_beads()` and `_handle_sase_plan()` to run **before** `_run_precommit()`. This way the plan file is already
in `plans/YYYYMM/` when `just fix` → `fmt-md` → prettier runs, and it gets formatted along with all other markdown
files.

This reordering is safe because:

- `_handle_beads()` closes/syncs beads and modifies the commit message — no dependency on precommit
- `_handle_sase_plan()` copies the plan file and modifies the commit message — no dependency on precommit
- Neither method depends on the other's output
- The precommit command (`just fix`) should logically run **after** all files are in their final locations, so it can
  validate/format the complete set of changes

### Change

**File**: `src/sase/workflows/commit/workflow.py`, method `CommitWorkflow.run()`

Swap lines so that the bead/plan block runs before the precommit call:

```python
# Before (current):
if not self._run_precommit(cwd):
    return False
if self._method != "create_proposal":
    self._handle_beads(cwd)
    self._handle_sase_plan(cwd)

# After (fixed):
if self._method != "create_proposal":
    self._handle_beads(cwd)
    self._handle_sase_plan(cwd)
if not self._run_precommit(cwd):
    return False
```

Update the comment above `_run_precommit` to reflect the new ordering.
