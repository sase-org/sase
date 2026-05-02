---
create_time: 2026-03-27 02:26:36
status: done
prompt: sdd/prompts/202603/debug_fix_just_flattening.md
---

# Plan: Debug and fix `sase/fix_just` workflow flattening failure

## Root Cause Analysis

### Code path trace for `#gh:sase #sase/fix_just`

When the lumberjack chop fires with prompt `#gh:sase #sase/fix_just`:

1. `launch_agent_from_cwd(chop.agent)` resolves VCS ref `#gh:sase`
2. Sets `update_target = ""` (launcher.py:305) — **no workspace sync happens**
3. `get_workspace_directory_for_num()` → `ensure_git_clone()` → only fetches on first creation
4. `run_agent_runner.py:157`: `if update_target and not is_home_mode:` → **False**, skips `prepare_workspace()`
5. `os.chdir(workspace_dir)` → CWD is the workspace

Then in `_flatten_anonymous_workflow`:

6. Fast path: `parse_workflow_reference("gh:sase #sase/fix_just")` → `wf_name="gh"`,
   `positional_args=["sase #sase/fix_just"]`
7. `"gh" in prompts` → True, `has_prompt_part()` → True
8. `has_extra_refs = True` (positional args contain `#`) → falls through to **slow path**
9. Slow path: `_find_standalone_workflow_ref()` scans regex for `#name` patterns
10. Finds `#gh` (has_prompt_part=True, skipped) and `#sase/fix_just`
11. **Critical check**: `"sase/fix_just" in prompts` — requires `fix_just` to be loaded from CWD `xprompts/` AND
    namespaced with project `"sase"`

### What makes `"sase/fix_just"` missing from prompts

The namespacing in `_load_workflows_from_files` (workflow_loader.py:291) requires:

- `project` is truthy (non-None, non-empty)
- `is_local` is True (file discovered from CWD-relative `xprompts/` or `.xprompts/`)

**Scenario A — Stale workspace**: `xprompts/fix_just.yml` doesn't exist in the workspace's working tree (stale clone,
behind master). No workspace sync is performed before the run (see step 4 above).

**Scenario B — Wrong project name**: `project_name` is not `"sase"` → namespacing creates `"<wrong>/fix_just"` instead
of `"sase/fix_just"`.

**Current evidence**: All 13 workspaces currently have `fix_just.yml` and are on recent commits. But the bug was
observed on 2026-03-26. The workspaces may have been synced since then. The lack of `prepare_workspace()` call means
workspaces only get the latest code if they happen to be on a recent commit.

## Implementation Plan

### Step 1: Write a diagnostic script to exercise the code path

Write a Python script that:

- Imports `_flatten_anonymous_workflow` and supporting functions
- Creates mock workflow objects matching `#gh:sase` and `sase/fix_just`
- Exercises the code path with both working (file present) and broken (file missing) scenarios
- Confirms which code path is taken and what logs are emitted

This validates our understanding without launching a real agent.

### Step 2: Run `get_all_prompts` from workspace CWDs to verify namespace behavior

Write a quick diagnostic that:

- Changes to each workspace directory
- Calls `get_all_prompts(project="sase")`
- Checks if `"sase/fix_just"` is in the result
- Also calls `detect_project()` to see what it returns

### Step 3: Fix the root cause

The fix should address both the **immediate bug** (stale workspaces) and add **defense-in-depth** (better error handling
when flattening fails).

**Fix A — Ensure workspace freshness for chop agent runs**:

In `launch_agent_from_cwd()` (launcher.py), when `vcs_ref` is detected and `update_target` is empty, set `update_target`
to a sensible default (e.g., `"origin/master"` or the default branch) so that `prepare_workspace()` runs and syncs the
workspace. Or: add a `git pull` step in `get_workspace_directory_for_num` when the workspace is being reused.

**Fix B — Fall back to non-namespaced lookup when namespaced lookup fails**:

In `_find_standalone_workflow_ref` (workflow_runner.py), when `name not in prompts`, try stripping the project prefix
and checking if the bare name exists. If found, log a warning and use the non-namespaced version. This handles the case
where the file exists outside CWD (e.g., in `~/.config/sase/xprompts/sase/`) but not in the workspace.

**Fix C (recommended) — Add update_target for VCS-ref chop runs**:

In `launch_agent_from_cwd()`, when a VCS ref like `#gh:sase` is resolved, set `update_target` to the ref value (the
branch name). This way the workspace checkout step will run `git checkout <branch>` + `git pull`, ensuring the workspace
has the latest code.

### Step 4: Verify the fix

1. Run `just lint` and `just test`
2. Manually trigger: `.venv/bin/sase run '#gh:sase #sase/fix_just'` or write a targeted test
3. Check diagnostic logs confirm workflow is found and flattened
4. Check artifacts show `workflow-fix_just-*` files (not `workflow-tmp_*`)

## Files to Modify

1. `src/sase/agent/launcher.py` — Set `update_target` for VCS-ref agent launches (Fix C)
2. `src/sase/xprompt/workflow_runner.py` — Add fallback for non-namespaced lookup (Fix B, optional defense-in-depth)
3. Tests for the fix

## Risk Assessment

- Fix C is the simplest and most direct: just ensuring the workspace is synced before every agent run
- Fix B is defense-in-depth but changes lookup semantics and could have unexpected interactions
- Both can be implemented independently
