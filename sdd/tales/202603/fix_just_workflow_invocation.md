---
create_time: 2026-03-27 02:07:41
status: done
prompt: sdd/prompts/202603/fix_just_workflow_invocation.md
---

# Plan: Fix `sase/fix_just` xprompt workflow not being invoked from chop

## Problem Statement

When the `sase_fix_just` lumberjack chop runs with `agent: "#gh:sase #sase/fix_just"`, the `sase/fix_just` xprompt YAML
workflow (defined in `xprompts/fix_just.yml`) is sometimes NOT invoked as a multi-step workflow. Instead,
`#sase/fix_just` passes through as literal text sent to the LLM.

## Root Cause Analysis

### Evidence

Artifact analysis of all `#gh:sase #sase/fix_just` ace-run directories reveals two patterns:

**Working runs** (workflow flattened, multi-step execution):

- `20260326131846`, `20260326141322`, `20260326191526`, `20260326201542`
- Have files like `workflow-fix_just-fix_linters_prompt.md` (named after the workflow step)

**Broken runs** (workflow NOT flattened, literal text sent to LLM):

- `20260326131300` - confirmed: `workflow-tmp_260326_131301-main_prompt.md` contains literal `#sase/fix_just` text, and
  the agent responded to it as free-text

**Ambiguous runs** (only `agent_meta.json` + `raw_xprompt.md`):

- `20260326151341`, `20260326161416`, `20260326171422`, `20260326181441`, `20260326211547`, `20260326221641`,
  `20260326231654`, `20260327001705`
- Could be successful (bash pre-steps passed, no agent steps needed, auto-dismiss cleaned up artifacts) OR could be
  broken (flattening failed, LLM got literal text and exited quickly)

### The Flattening Code Path

The critical function is `_flatten_anonymous_workflow()` in `src/sase/xprompt/workflow_runner.py:131-242`.

For the prompt `"#gh:sase #sase/fix_just"`:

1. **Fast path** (line 192): Parses first `#` reference → `#gh` with colon arg `sase`
2. **Lookup** (line 195): Checks if `"gh"` is in `get_all_prompts(project=project)` → Yes (VCS workflow from sase-github
   plugin)
3. **Prompt part check** (line 200): `gh` workflow has `prompt_part` → enters this branch
4. **Extra refs check** (line 207): `positional_args=["sase"]`, no `#` in args → False
5. **Standalone scan** (line 217): Calls `_find_standalone_workflow_ref(prompt_text, prompts)`
6. **This function** (line 76-83): Scans ALL `#name` references, filters for those in `prompts` that DON'T have
   `prompt_part`. Requires EXACTLY 1 match to succeed.

**Failure condition**: If `"sase/fix_just"` is NOT in `prompts`, the standalone scan finds 0 matches → returns None →
flattening fails → falls through to line 222 which returns None.

### Why `sase/fix_just` might be missing from `prompts`

`get_all_prompts(project=project)` calls `get_all_workflows(project=project)` which calls
`_load_workflows_from_files(project=effective_project)` which uses `Path.cwd()` to discover `xprompts/*.yml` files.

Confirmed: `os.chdir(workspace_dir)` IS called before `execute_workflow()` (line 171 of `run_agent_runner.py`), and the
file exists in all workspaces.

However, `_flatten_anonymous_workflow` has **zero logging** when flattening fails at line 222. The debug logs at lines
178, 231, 237, 241 exist for the slow path but NOT for the specific case where the fast-path `has_prompt_part` branch
falls through to `return None`.

**Most likely root cause**: There is a race condition or transient state where `sase/fix_just` is not in the prompts
dict. Possible causes:

- The workspace CWD contains a stale clone that doesn't have the file yet (especially right after the rename from
  `fix_just_all.yml` to `fix_just.yml`)
- The `detect_project()` call returns an unexpected value
- A file system race when the workspace is being synced

### Secondary issue: silent fallthrough

When `_flatten_anonymous_workflow` returns None at line 222, the prompt falls through to
`_expand_embedded_workflows_in_prompt()` (line 114 in `workflow_executor_steps_embedded_expand.py`) which explicitly
skips workflows without `prompt_part`: `if not workflow.has_prompt_part(): continue`. This means `#sase/fix_just`
becomes literal text with NO warning.

## Implementation Plan

### Phase 1: Add diagnostic logging (required)

**File**: `src/sase/xprompt/workflow_runner.py`

Add debug logging at the critical failure point in `_flatten_anonymous_workflow`:

1. After line 176 (`prompts = get_all_prompts(project=project)`): Log the project, CWD, and whether `sase/fix_just` is
   in the prompts keys
2. At line 222 (the `return None` inside the `has_prompt_part()` branch): Log that the fast-path standalone scan failed,
   including the prompt text and available prompt keys matching the `sase/` prefix

This will confirm whether the issue is prompts-missing or pattern-matching.

### Phase 2: Add diagnostic logging to embedded expansion (required)

**File**: `src/sase/xprompt/workflow_executor_steps_embedded_expand.py`

At line 114-115 (`if not workflow.has_prompt_part(): continue`): Add a warning log when a workflow reference is found
but skipped because it has no `prompt_part`. This is currently completely silent and makes the bug invisible.

### Phase 3: Fix the root cause (after Phase 1 confirms)

**Option A: Improve workspace freshness** - If the issue is stale workspaces, add a git pull or sync step before
launching agent chops.

**Option B: Add a fallback in `_expand_embedded_workflows_in_prompt`** - When a workflow reference has no `prompt_part`
but IS a standalone multi-step workflow, instead of silently skipping it, raise an error or log a clear warning that the
workflow could not be invoked as an embedded reference.

**Option C: Make `_flatten_anonymous_workflow` more robust** - If the standalone scan fails because `sase/fix_just`
isn't in prompts, try loading workflows directly from the filesystem as a fallback (bypassing the CWD-based discovery).

### Phase 4: Verify the fix

After implementing changes, trigger the chop manually or wait for the next lumberjack cycle. Check:

1. The new debug logs confirm the workflow is found in prompts
2. The artifacts directory shows `workflow-fix_just-*` files (not `workflow-tmp_*`)
3. Run `just lint` and `just test` to confirm they pass

## Files to Modify

1. `src/sase/xprompt/workflow_runner.py` - Add logging (Phase 1)
2. `src/sase/xprompt/workflow_executor_steps_embedded_expand.py` - Add logging (Phase 2)
3. Possibly `src/sase/xprompt/workflow_loader.py` or `src/sase/agent/launcher.py` (Phase 3)

## Testing

- Run `just lint` and `just test` after changes
- Manually trigger the chop: `.venv/bin/sase axe chop sase_fix_just` (if supported)
- Or launch directly: `.venv/bin/sase run '#gh:sase #sase/fix_just'`
- Check the debug logs and artifacts to confirm flattening works
