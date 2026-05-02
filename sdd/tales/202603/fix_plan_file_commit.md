---
create_time: 2026-03-27 13:12:40
status: done
prompt: sdd/prompts/202603/fix_plan_file_commit.md
---

# Plan: Fix plan file not being committed to PR branch after approval

## Problem

When an agent's plan is approved, the plan file should be committed to the PR branch (as a version-controlled SDD file).
For PR #29 (`sase_restart_axe_1`), the plan file was never committed anywhere — not to the PR branch, not to master. The
plan exists only in the `~/.sase/plans/` archive.

Evidence from the PR:

- No `plans/restart_axe.md` or `specs/restart_axe.md` in PR changed files
- No `chore: Add SDD spec and plan for restart_axe` commit on the branch
- No `PLAN=` metadata in the commit message
- Plan file not found on the default branch either (404)

## Root Cause

There is a chain of silent failures in `src/sase/axe/run_agent_exec_plan.py` lines 207-222:

```python
sdd_plan_name: str | None = None
version_controlled = True
sdd_dir = Path(ctx.workspace_dir)
try:
    version_controlled = get_sdd_config()                           # 1
    sdd_dir = get_sdd_dir(...)                                      # 2
    sdd_plan_name = os.path.splitext(os.path.basename(...))[0]      # 3  ← sets "restart_axe"
    expanded = expand_prompt_for_spec(state.original_prompt)         # 4  ← FAILS HERE (likely)
    sdd_spec_path_obj, _ = write_sdd_files(...)                     # 5  ← never reached
    ...
except Exception:
    pass  # Silent swallow
```

When an exception occurs at step 4 (`expand_prompt_for_spec`) or step 5 (`write_sdd_files`), `sdd_plan_name` is already
set to `"restart_axe"` but the SDD files were never written. Then the subsequent code behaves as if SDD partially
succeeded:

1. **`_commit_sdd_files` finds no files** (lines 285-287): Called because `sdd_plan_name` is set and
   `version_controlled` is True. But it checks `os.path.exists()` on the expected file paths, finds nothing, and returns
   early without error.

2. **`SASE_PLAN` points to a non-existent file** (lines 291-292): Set to `{workspace}/plans/restart_axe.md` which was
   never written.

3. **`_handle_sase_plan` returns early** (workflow.py line 174): Checks `os.path.isfile(plan_path)`, finds the file
   doesn't exist, and returns — no `PLAN=` metadata, no `_plan_path` staging.

Result: the plan file is completely absent from the commit.

### Secondary issue: fallback path can't stage external files

If the SDD block had failed at step 1 or 2 (before `sdd_plan_name` was set), the fallback path would set
`SASE_PLAN = ~/.sase/plans/restart_axe.md` (the archive copy outside the repo). Then `_handle_sase_plan` would try to
stage it via `git add`, which silently fails because the file is outside the repo. This is a second bug — the fallback
path can never work.

## Fix

### 1. `_handle_sase_plan` — copy plan into repo when outside or missing (primary fix)

**File:** `src/sase/workflows/commit/workflow.py` — `_handle_sase_plan()`

When `SASE_PLAN` points to a file outside the repo (or to a non-existent in-repo path), copy the plan into the repo
before staging:

```python
def _handle_sase_plan(self, cwd: str) -> None:
    plan_path = os.environ.get("SASE_PLAN", "")
    if not plan_path:
        return

    repo_root = self._get_repo_root(cwd)
    in_repo = repo_root and plan_path.startswith(repo_root + "/")

    # If plan file doesn't exist at the expected path, try the ~/.sase/plans/ archive
    if not os.path.isfile(plan_path):
        archive_fallback = os.path.join(
            os.path.expanduser("~"), ".sase", "plans", os.path.basename(plan_path)
        )
        if os.path.isfile(archive_fallback):
            plan_path = archive_fallback
            in_repo = False  # archive is outside repo
        else:
            return  # truly missing

    # If plan is outside repo, copy it in
    if not in_repo:
        dest = os.path.join(cwd, "plans", os.path.basename(plan_path))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(plan_path, dest)
        plan_path = dest

    # (rest of existing logic: compute plan_rel, append PLAN=, sed, set _plan_path)
    ...
```

This handles both failure modes:

- SDD partially failed → `SASE_PLAN` points to non-existent in-repo file → falls back to archive copy → copies into repo
- SDD completely failed → `SASE_PLAN` points to archive copy → copies into repo

### 2. Log exceptions in SDD block instead of silently passing

**File:** `src/sase/axe/run_agent_exec_plan.py` — lines 221-222

Change `except Exception: pass` to log the exception:

```python
except Exception:
    _logger.warning("SDD file generation failed", exc_info=True)
```

This preserves the "best effort" semantics while providing observability for future debugging.

### 3. Add `import shutil` to workflow.py

**File:** `src/sase/workflows/commit/workflow.py`

Add `import shutil` to the imports for the `copy2` call in fix #1.

## Changes Summary

| File                                    | Change                                                                                                   |
| --------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `src/sase/workflows/commit/workflow.py` | `_handle_sase_plan`: add fallback to `~/.sase/plans/` archive + copy-into-repo when plan is outside repo |
| `src/sase/axe/run_agent_exec_plan.py`   | Log SDD block exceptions instead of silently passing                                                     |

## Testing

- **Unit test**: `_handle_sase_plan` with `SASE_PLAN` pointing to:
  1. An in-repo file (existing behavior, should still work)
  2. A non-existent in-repo file with archive fallback available
  3. A file outside the repo (archive path directly)
  4. A completely missing file (no archive either — returns early)
- **Integration**: Verify `_plan_path` is set correctly in all cases
- Existing tests should continue to pass
