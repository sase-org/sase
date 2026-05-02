---
create_time: 2026-03-27 13:29:30
status: done
prompt: sdd/prompts/202603/fix_sdd_frontmatter_and_spec.md
---

# Plan: Fix plan frontmatter and spec file not being committed when SDD block fails

## Problem

When the SDD block in `run_agent_exec_plan.py` fails (specifically when `expand_prompt_for_spec()` throws), two things
go wrong:

1. **Plan file committed without frontmatter** — `write_sdd_files()` (which adds `create_time`/`status` via
   `add_create_time_frontmatter()`) is never reached. The fallback in `_handle_sase_plan` copies the raw archive from
   `~/.sase/plans/` which has no frontmatter (since `save_plan_to_sase()` does a raw `shutil.copy2()`).

2. **Spec file never created** — `expand_prompt_for_spec()` fails before `write_sdd_files()` runs, so the spec is never
   written. There's no fallback for the spec file anywhere.

## Root Cause Chain

```
save_plan_to_sase() → raw copy to ~/.sase/plans/ (NO frontmatter)
                    ↓
SDD block:
  expand_prompt_for_spec()  → FAILS (exception)
  write_sdd_files()         → NEVER REACHED (would add frontmatter + write spec)
                    ↓
_commit_sdd_files()  → finds no files, returns early
                    ↓
SASE_PLAN = {workspace}/plans/{name}.md (doesn't exist)
                    ↓
_handle_sase_plan() fallback:
  → copies archive (no frontmatter) into repo
  → sed for status:wip→done does nothing
  → no spec file handling at all
```

## Fix

### 1. Isolate spec expansion failure from plan file creation (primary fix)

**File:** `src/sase/axe/run_agent_exec_plan.py` — SDD block (lines 213-225)

Wrap `expand_prompt_for_spec()` in its own try/except so that a spec expansion failure falls back to the raw prompt
instead of preventing `write_sdd_files()` from running at all:

```python
sdd_plan_name: str | None = None
version_controlled = True
sdd_dir = Path(ctx.workspace_dir)
try:
    version_controlled = get_sdd_config()
    sdd_dir = get_sdd_dir(ctx.workspace_dir, ctx.workspace_num, version_controlled)
    sdd_plan_name = os.path.splitext(os.path.basename(plan_result.plan_file))[0]
    try:
        expanded = expand_prompt_for_spec(state.original_prompt)
    except Exception:
        logger.warning("Spec prompt expansion failed, using raw prompt", exc_info=True)
        expanded = state.original_prompt
    sdd_spec_path_obj, _ = write_sdd_files(
        sdd_dir, sdd_plan_name, expanded, plan_result.plan_file
    )
    state.sdd_spec_path = str(sdd_spec_path_obj)
    if not version_controlled:
        commit_sdd_files(sdd_dir, f"Add SDD files for {sdd_plan_name}")
except Exception:
    logger.warning("SDD file generation failed", exc_info=True)
```

This ensures `write_sdd_files()` runs even when spec expansion fails, so:

- The plan file gets frontmatter (via `add_create_time_frontmatter()`)
- The spec file gets created (with raw prompt as content)
- `_commit_sdd_files` finds the files and commits them

### 2. Add frontmatter in `_handle_sase_plan` fallback (defensive fix)

**File:** `src/sase/workflows/commit/workflow.py` — `_handle_sase_plan()`

After copying the plan file into the repo (the `if not in_repo:` block), check if frontmatter is missing and add it:

```python
# If plan is outside repo, copy it in
if not in_repo:
    dest = os.path.join(cwd, "plans", os.path.basename(plan_path))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(plan_path, dest)
    plan_path = dest

# Ensure plan has frontmatter (may be missing if SDD block failed)
plan_content = Path(plan_path).read_text(encoding="utf-8")
if not plan_content.startswith("---\n"):
    from sase.llm_provider._plan_utils import add_create_time_frontmatter
    Path(plan_path).write_text(
        add_create_time_frontmatter(plan_content), encoding="utf-8"
    )
```

This is defensive — with fix #1, the SDD block should succeed and the plan will already have frontmatter. But if some
other failure path leads here without frontmatter, it gets added.

## Changes Summary

| File                                    | Change                                                                             |
| --------------------------------------- | ---------------------------------------------------------------------------------- |
| `src/sase/axe/run_agent_exec_plan.py`   | Isolate `expand_prompt_for_spec()` in inner try/except, falling back to raw prompt |
| `src/sase/workflows/commit/workflow.py` | Add frontmatter to plan file in `_handle_sase_plan` if missing                     |

## Testing

- Existing tests should continue to pass
- **Unit test**: `write_sdd_files` with raw prompt content (verify it still adds frontmatter)
- **Unit test**: `_handle_sase_plan` with archive file lacking frontmatter (verify frontmatter is added)
- Verify that `_commit_sdd_files` now finds both files when spec expansion fails but write succeeds
