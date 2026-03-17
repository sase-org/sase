# Plan: Migrate mentor, CRS, and fix-hook to `#hg` Embedded Workflow

## Context

The mentor, CRS, and fix-hook agents currently contain explicit Python code for workspace management (claiming via
RUNNING field, `os.chdir()`, `sase_hg_clean`, `sase_hg_update`, and releasing). A new `#hg` embedded workflow
(`~/xprompts/hg.yml`) was recently added that handles all of this declaratively: it claims a workspace, changes
directory via `_chdir`, cleans and updates the workspace, and releases it after the agent finishes.

**Goal**: Migrate the three agents to use `#hg(cl_name)` in their prompts instead of the explicit workspace management
code. This removes ~100+ lines of duplicated workspace logic from the Python files.

**Key constraint**: The `_chdir` special output is already supported in the full `WorkflowExecutor` but NOT in
`execute_standalone_steps()` (used by `expand_embedded_workflows_in_query()`). This must be added first, or `#hg`'s
workspace directory change won't work when embedded.

---

## Phase 1: Foundation — `_chdir` support + xprompt updates

### 1a. Add `_chdir` to `execute_standalone_steps()`

**File**: `src/sase/main/query_handler/_query.py`

In `execute_standalone_steps()`, after parsing step output for both bash steps (~line 270) and python steps (~line 297),
add:

```python
# Handle _chdir special output: change executor's working directory
if "_chdir" in output:
    chdir_path = str(output.pop("_chdir"))
    if not os.path.isabs(chdir_path):
        chdir_path = os.path.abspath(chdir_path)
    os.chdir(chdir_path)
```

This mirrors the existing pattern in `workflow_executor_steps_script.py:192-197` and `:326-331`.

### 1b. Update xprompts

**File**: `xprompts/mentor.md`

Add `cl_name: word` input and `#hg:{{ cl_name }}` before the role section:

```yaml
---
name: mentor
input:
  - name: prompt
    type: text
  - name: cl_name
    type: word
---
#hg:{{ cl_name }}

### Role
...
```

**File**: `xprompts/crs.md`

Add `cl_name: word` input and `#hg:{{ cl_name }}` before the prompt body:

```yaml
---
name: crs
input:
  - name: critique_comments_path
    type: path
  - name: cl_name
    type: word
---
#hg:{{ cl_name }}

Can you help me address the Critique comments?...
```

**File**: `xprompts/fix_hook.md`

Add `cl_name: word` input and `#hg:{{ cl_name }}` before the prompt body:

```yaml
---
name: fix_hook
input:
  - name: hook_command
    type: line
  - name: output_file
    type: path
  - name: cl_name
    type: word
---
#hg:{{ cl_name }}

The command `{{ hook_command }}` is failing...
```

### 1c. Verification

- `just check` passes (fmt, lint, test)
- Write a unit test for `_chdir` in `execute_standalone_steps()` — create a step with `_chdir` output, verify
  `os.getcwd()` changes
- Xprompt updates are additive and don't break existing callers (the old callers don't pass `cl_name` yet, which will
  cause an error only if they're invoked — but they won't be until Phase 2+)

### Key files

| File                                    | Change                                        |
| --------------------------------------- | --------------------------------------------- |
| `src/sase/main/query_handler/_query.py` | Add `_chdir` handling (~6 lines, 2 locations) |
| `xprompts/mentor.md`                    | Add `cl_name` input + `#hg:{{ cl_name }}`     |
| `xprompts/crs.md`                       | Add `cl_name` input + `#hg:{{ cl_name }}`     |
| `xprompts/fix_hook.md`                  | Add `cl_name` input + `#hg:{{ cl_name }}`     |

---

## Phase 2: Migrate mentor workflow

### How the mentor prompt currently works

`MentorConfig.prompt` from `~/.config/sase/sase.yml` is an xprompt reference (e.g., `#mentor/code_review`).
`_build_mentor_prompt()` calls `process_xprompt_references(mentor.prompt)` to expand it. The expanded result typically
contains `#propose` (from `mentor.md`). Then `expand_embedded_workflows_in_query()` handles `#propose`.

### 2a. Update `_build_mentor_prompt()` to inject `#hg`

**File**: `src/sase/mentor_workflow.py`

Change `_build_mentor_prompt()` to accept `cl_name` and prepend `#hg:cl_name` to the expanded prompt:

```python
def _build_mentor_prompt(mentor: MentorConfig, cl_name: str) -> str:
    expanded = process_xprompt_references(mentor.prompt)
    return f"#hg:{cl_name}\n\n{expanded}"
```

This adds `#hg` _after_ xprompt expansion but _before_ embedded workflow expansion, so
`expand_embedded_workflows_in_query()` will process both `#hg` and `#propose`.

**Ordering note**: `#hg` appears before `#propose` in the text. `expand_embedded_workflows_in_query()` processes matches
last-to-first, so:

- `#propose` pre-steps run first (none — `#propose` has no pre-steps)
- `#hg` pre-steps run second (setup + prepare → claim workspace, chdir, clean, checkout)
- Post-steps execute in order: `#propose` post-steps first (create proposal), then `#hg` release (release workspace)
- This is correct: proposal is created while still in the workspace, then workspace is released.

### 2b. Remove explicit workspace management from `MentorWorkflow.run()`

**File**: `src/sase/mentor_workflow.py`

Remove from `run()`:

- Workspace claiming logic (lines 163-198): `get_first_available_workspace()`, `get_workspace_directory_for_num()`,
  `claim_workspace()`
- `os.chdir(workspace_dir)` (line 215)
- `run_sase_hg_clean()` and `provider.checkout()` (lines 218-237)
- `os.chdir(original_dir)` in finally block (line 343)
- `release_workspace()` in finally block (lines 345-351)
- Constructor params: `workspace_num`, `workflow_name`, `workspace_dir`
- Instance vars: `_owns_workspace`, `_workspace_num`, `_workflow_name`, `_workspace_dir`

Remove unused imports:

- `claim_workspace`, `get_first_available_workspace`, `get_workspace_directory_for_num`, `release_workspace` from
  `running_field`
- `run_sase_hg_clean` from `commit_utils`
- `get_vcs_provider` from `vcs_provider`

**Keep**: `_find_changespec_by_name()` — still needed to find `project_file` and `project_name` for artifacts directory.

### 2c. Update `axe_mentor_runner.py`

**File**: `src/sase/axe_mentor_runner.py`

The runner currently receives `workspace_dir` and `workspace_num` as CLI args and passes them to `MentorWorkflow`. Since
`MentorWorkflow` no longer manages workspaces:

- Remove `workspace_dir`, `workspace_num`, `workflow_name` from CLI args
- Remove `release_workspace()` from finally block
- Keep status update logic (`set_mentor_status()`) and completion marker
- Keep SIGTERM handler (for status update safety, not workspace release)

**Important**: The axe scheduler that launches `axe_mentor_runner.py` must also stop pre-claiming workspaces for mentor
runs. Identify and update the scheduler code (likely in the TUI/ace layer or the axe module). The scheduler should stop
calling `claim_workspace()` / `get_first_available_axe_workspace()` for mentor launches.

### 2d. Verification

- Run mentor workflow manually: `sase mentor code:some_mentor --cl my_cl`
- Verify workspace is claimed/prepared by `#hg`, agent runs in correct directory, workspace is released
- `just check` passes

### Key files

| File                                                             | Change                                                       |
| ---------------------------------------------------------------- | ------------------------------------------------------------ |
| `src/sase/mentor_workflow.py`                                    | Remove workspace management, update `_build_mentor_prompt()` |
| `src/sase/axe_mentor_runner.py`                                  | Remove workspace CLI args and release                        |
| Axe scheduler (TBD — find the code that launches mentor runners) | Stop pre-claiming workspaces                                 |

---

## Phase 3: Migrate CRS workflow

### 3a. Update CRS prompt building to pass `cl_name`

**File**: `src/sase/crs_workflow.py`

In `_build_crs_prompt()`, add `cl_name` parameter:

```python
def _build_crs_prompt(critique_comments_path: str, cl_name: str) -> str:
    escaped_path = escape_for_xprompt(critique_comments_path)
    escaped_cl = escape_for_xprompt(cl_name)
    prompt_text = f'#crs(critique_comments_path="{escaped_path}", cl_name="{escaped_cl}")'
    return process_xprompt_references(prompt_text)
```

Update `CrsWorkflow.__init__()` to accept `cl_name: str` parameter. Update `CrsWorkflow.run()` to pass `cl_name` to
`_build_crs_prompt()`.

### 3b. Update `axe_crs_runner.py`

**File**: `src/sase/axe_crs_runner.py`

- Remove `os.chdir(workspace_dir)` (line 80) — `#hg` handles this
- Remove workspace-related CLI args (`workspace_dir`, `workspace_num`, `workflow_name`)
- In `finalize_axe_runner()` call: remove `workspace_num` and `workflow_name` args, or keep a simplified version that
  only updates suffixes and writes completion markers (no workspace release)
- Pass `cl_name` (= `changespec_name`) to `CrsWorkflow`

**Important**: Update `finalize_axe_runner()` or create a new variant that skips workspace release since `#hg` handles
it.

### 3c. Update axe scheduler for CRS

Find and update the code that launches `axe_crs_runner.py` to stop pre-claiming workspaces.

### 3d. Verification

- Test CRS workflow via axe runner
- Verify workspace lifecycle managed by `#hg`
- `just check` passes

### Key files

| File                           | Change                                                                                      |
| ------------------------------ | ------------------------------------------------------------------------------------------- |
| `src/sase/crs_workflow.py`     | Add `cl_name` parameter, pass to `#crs(...)`                                                |
| `src/sase/axe_crs_runner.py`   | Remove workspace management, pass `cl_name` to CrsWorkflow                                  |
| `src/sase/axe_runner_utils.py` | Consider splitting `finalize_axe_runner()` to separate suffix update from workspace release |
| Axe scheduler (TBD)            | Stop pre-claiming workspaces for CRS                                                        |

---

## Phase 4: Migrate fix-hook workflow

### 4a. Update fix-hook prompt building to pass `cl_name`

**File**: `src/sase/axe_fix_hook_runner.py`

Update the prompt building (lines 129-134) to include `cl_name`:

```python
prompt_ref = (
    f'#fix_hook(hook_command="{escaped_cmd}", '
    f'output_file="{escaped_output}", '
    f'cl_name="{changespec_name}")'
)
```

### 4b. Remove explicit workspace management

**File**: `src/sase/axe_fix_hook_runner.py`

- Remove `os.chdir(workspace_dir)` (line 121) — `#hg` handles this
- Remove workspace-related CLI args
- Update `finalize_axe_runner()` call to skip workspace release (same approach as Phase 3)

### 4c. Update axe scheduler for fix-hook

Find and update the code that launches `axe_fix_hook_runner.py`.

### 4d. Verification

- Test fix-hook workflow via axe runner
- `just check` passes

### Key files

| File                              | Change                                               |
| --------------------------------- | ---------------------------------------------------- |
| `src/sase/axe_fix_hook_runner.py` | Add `cl_name` to prompt, remove workspace management |
| Axe scheduler (TBD)               | Stop pre-claiming workspaces for fix-hook            |

---

## Phase 5: Cleanup

### 5a. Simplify `finalize_axe_runner()`

**File**: `src/sase/axe_runner_utils.py`

If all three runners no longer need workspace release in their finalize step, simplify `finalize_axe_runner()` to only
handle suffix updates and completion markers. Remove `release_workspace()` call and the `workspace_num`/`workflow_name`
parameters.

### 5b. Remove `prepare_workspace()` if unused

**File**: `src/sase/axe_runner_utils.py`

If `prepare_workspace()` (lines 38-78) is no longer called by any runner, remove it.

### 5c. Remove dead imports and constructor params

Sweep all modified files for unused imports (`running_field`, `commit_utils`, `vcs_provider`).

### 5d. Final verification

- `just check` passes
- Run each workflow end-to-end (mentor, CRS, fix-hook) both interactively and via axe
- Verify workspaces are properly claimed and released (check RUNNING field)
- Verify proposals are created correctly

### Key files

| File                           | Change                                                         |
| ------------------------------ | -------------------------------------------------------------- |
| `src/sase/axe_runner_utils.py` | Simplify `finalize_axe_runner()`, remove `prepare_workspace()` |
| All modified files             | Dead import cleanup                                            |

---

## Critical implementation notes

1. **`execute_standalone_steps()` `_chdir` support is a prerequisite** — without it, `#hg`'s workspace directory change
   won't propagate to subsequent steps or the agent invocation.

2. **Expansion ordering is safe**: `#hg` (no pre-steps for `#propose`, setup+prepare pre-steps for `#hg`) runs
   correctly. Post-steps execute `#propose` first (proposal while still in workspace), then `#hg` release.

3. **Axe scheduler must stop pre-claiming**: Each phase must find and update the axe scheduler code that launches the
   respective runner. Look for `get_first_available_axe_workspace()` and `claim_workspace()` calls in the TUI/ace layer.

4. **Error handling**: `#hg`'s release step runs as a post-step. If the process is killed before post-steps execute, the
   workspace may leak. Consider keeping a safety-net `release_workspace()` keyed by PID in the runner's finally block,
   or accept the risk since stale RUNNING entries can be cleaned via PID checks.

5. **Reuse existing functions**: `escape_for_xprompt()` from `sase.xprompt` for safe argument embedding;
   `_find_changespec_by_name()` for resolving CL names.
