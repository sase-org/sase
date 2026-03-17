# Plan: Replace ProjectSelectModal with `#hg` Embedded Workflow

## Context

The `sase ace` TUI has a `ProjectSelectModal` (triggered by `at` keybinding) that prompts the user to select a project
or ChangeSpec, then allocates a workspace, cleans it, checks out the target revision, and launches a background agent.
This modal-based flow is being replaced with the `#hg` embedded workflow, where the user types `#hg(cl_name)` directly
in their prompt.

The `#hg` workflow will handle: workspace claiming (RUNNING field), directory change, workspace preparation (clean +
checkout), and workspace release (post-step). The prompt_part will be empty.

### Key Technical Constraint

Python workflow steps run via `subprocess.run()` (not `exec()`), so `os.chdir()` in a pre-step does NOT affect the
parent executor process. To support `#hg` changing the working directory, we need to add a `_chdir` mechanism to the
workflow executor.

---

## Phase 1: Foundation — `_chdir` executor support + `hg.yml` workflow

### 1a. Add `_chdir` special output to workflow executor

When a step outputs a key named `_chdir` with a path value, the executor calls `os.chdir()` in its own process after the
step completes. This makes all subsequent steps (including the prompt/LLM step) run in the new working directory.

**File:** `src/sase/xprompt/workflow_executor_steps_script.py`

- After step output is parsed (~line 320), check for `_chdir` key
- If present: call `os.chdir(value)`, log the change, remove `_chdir` from output dict

### 1b. Create `hg.yml` workflow

**File:** `~/.local/share/chezmoi/home/xprompts/hg.yml`

```yaml
input:
  - name: cl_name
    type: word

steps:
  - name: setup
    python: |
      # Resolve cl_name → project info, allocate workspace, claim it
      from sase.ace.changespec import find_all_changespecs
      from sase.running_field import (
          get_first_available_axe_workspace,
          get_workspace_directory_for_num,
          claim_workspace,
      )
      import os

      cl_name = {{ cl_name | tojson }}
      # Find ChangeSpec
      cs_match = None
      for cs in find_all_changespecs():
          if cs.name == cl_name:
              cs_match = cs
              break
      if not cs_match:
          raise RuntimeError(f"ChangeSpec '{cl_name}' not found")

      project_name = cs_match.project_basename
      project_file = cs_match.file_path

      # Allocate workspace
      workspace_num = get_first_available_axe_workspace(project_file)
      workspace_dir, _ = get_workspace_directory_for_num(workspace_num, project_name)

      # Claim workspace
      pid = os.getppid()  # Runner process PID
      workflow_name = f"hg-{cl_name}"
      claim_workspace(project_file, workspace_num, workflow_name, pid, cl_name)

      # Output values (including _chdir to change executor's cwd)
      print(f"project_name={project_name}")
      print(f"project_file={project_file}")
      print(f"workspace_dir={workspace_dir}")
      print(f"workspace_num={workspace_num}")
      print(f"_chdir={workspace_dir}")
    output:
      project_name: word
      project_file: path
      workspace_dir: path
      workspace_num: int

  - name: prepare
    bash: |
      # Clean workspace and checkout target
      sase_hg_clean "{{ setup.workspace_dir }}" "{{ cl_name }}-hg"
      sase_hg_update "{{ cl_name }}" "{{ setup.workspace_dir }}"
    output: { success: bool }

  - name: inject
    prompt_part: ""

  - name: release
    python: |
      from sase.running_field import release_workspace
      release_workspace(
          {{ setup.project_file | tojson }},
          {{ setup.workspace_num }},
          f"hg-{{ cl_name }}",
          {{ cl_name | tojson }},
      )
      print("released=true")
    output: { released: bool }
```

> **Note:** The exact `sase_hg_clean` and `sase_hg_update` invocation syntax will need verification against the actual
> script interfaces. The `prepare` step may need adjustment.

### 1c. Verification

- Run `chezmoi apply` to deploy `hg.yml` to `~/xprompts/`
- Test: `sase run '#hg(some_cl_name) describe what you see'` from any directory
- Verify: workspace is claimed, prepared, agent runs in workspace, workspace is released

### Key files

| File                                                 | Change                                   |
| ---------------------------------------------------- | ---------------------------------------- |
| `src/sase/xprompt/workflow_executor_steps_script.py` | Add `_chdir` output handling (~10 lines) |
| `~/.local/share/chezmoi/home/xprompts/hg.yml`        | New file                                 |

---

## Phase 2: TUI Integration — Bare prompt bar + `#hg` launch path

### 2a. Add bare prompt bar

**File:** `src/sase/ace/tui/actions/agent_workflow/_prompt_bar.py`

- Add `_show_bare_prompt_input_bar()` method: mounts the prompt bar with a minimal `PromptContext` (home-like defaults,
  no workspace resolution)
- The context signals "bare mode" — workspace info will come from `#hg` at runtime

### 2b. Rewire `at` keybinding

**File:** `src/sase/ace/tui/actions/agent_workflow/_entry_points.py`

- Modify `action_start_custom_agent()`: instead of pushing `ProjectSelectModal`, call `_show_bare_prompt_input_bar()`
- Remove the `on_project_select` callback and all modal-related imports

### 2c. Modify launch flow for bare mode

**File:** `src/sase/ace/tui/actions/_agent_workflow_launch.py`

- Modify `_finish_agent_launch()`: when `PromptContext.is_bare_mode` is True and prompt contains `#hg(...)`, skip
  workspace prep in the runner
- Modify `_launch_background_agent()`: when bare mode, launch runner from home dir (cwd=home) with minimal args, OR
  launch a simplified runner
- The runner skips `prepare_workspace()` and `claim_workspace()` — `#hg` handles both
- The runner's finally block: make `release_workspace()` conditional (skip if `#hg` handled release, or make release
  idempotent)

### 2d. Modify runner for bare/hg mode

**File:** `src/sase/axe_run_agent_runner.py`

- Add a flag (CLI arg or sentinel) to skip workspace preparation and claiming
- When flag is set, runner still chdir's if workspace_dir is provided (fallback), but does NOT call
  `prepare_workspace()` or `claim_workspace()`
- Alternatively: if launching from home with `#hg`, the runner doesn't chdir at all — `#hg`'s `_chdir` handles it

### 2e. Update `_types.py`

**File:** `src/sase/ace/tui/actions/agent_workflow/_types.py`

- Add `is_bare_mode: bool = False` to `PromptContext`

### 2f. Verification

- Press `at` in ace TUI → bare prompt bar appears (no modal)
- Type `#hg(some_cl) fix the bug` → agent launches in correct workspace
- Verify workspace is claimed, prepared, agent runs, workspace released
- `space` keybinding continues to work unchanged (existing flow)

### Key files

| File                                                       | Change                              |
| ---------------------------------------------------------- | ----------------------------------- |
| `src/sase/ace/tui/actions/agent_workflow/_prompt_bar.py`   | Add `_show_bare_prompt_input_bar()` |
| `src/sase/ace/tui/actions/agent_workflow/_entry_points.py` | Rewire `at` to bare prompt bar      |
| `src/sase/ace/tui/actions/_agent_workflow_launch.py`       | Handle bare mode launch             |
| `src/sase/axe_run_agent_runner.py`                         | Add skip-workspace-prep flag        |
| `src/sase/ace/tui/actions/agent_workflow/_types.py`        | Add `is_bare_mode` field            |

---

## Phase 3: Cleanup — Remove modal and dead code

### 3a. Delete modal

- Delete `src/sase/ace/tui/modals/project_select_modal.py`
- Remove `ProjectSelectModal` and `SelectionItem` exports from `src/sase/ace/tui/modals/__init__.py`

### 3b. Clean up references

- Remove all `ProjectSelectModal` / `SelectionItem` imports from `_entry_points.py`
- Remove the old `on_project_select` callback (if any remnants from Phase 2)
- Remove home-mode code paths if no longer needed (now that `at` uses bare prompt bar)

### 3c. Update help modal

- Update `src/sase/ace/tui/modals/help_modal.py` to reflect new `at` behavior (bare prompt bar, not project selection
  modal)

### 3d. Run checks

- `just check` — fmt, lint, test
- Manual test: verify `at`, `space`, and `#hg` all work end-to-end

### Key files

| File                                                       | Change                   |
| ---------------------------------------------------------- | ------------------------ |
| `src/sase/ace/tui/modals/project_select_modal.py`          | DELETE                   |
| `src/sase/ace/tui/modals/__init__.py`                      | Remove exports           |
| `src/sase/ace/tui/actions/agent_workflow/_entry_points.py` | Remove dead imports/code |
| `src/sase/ace/tui/modals/help_modal.py`                    | Update help text         |
