---
bead_id: sase-2tm
---

# Multi-File Panel Support for Agent Entries

## Context

Currently, each agent entry on the "CLs" (Agents) tab has at most one file (`diff_path`) displayed in the file panel. We
want to support multiple files per agent entry, navigable with ctrl+n / ctrl+p. The first use case: when a plan is
approved via the notification panel, save the plan file to `{workspace_dir}/.sase/plans/` and show it as an additional
file alongside the diff.

## Phase 1: Multi-File Data Model + File Panel Cycling (Foundation)

**Must complete before Phases 2 and 3.**

### 1a. Agent model — add `extra_files` field

**File:** `src/sase/ace/tui/models/agent.py`

- Add field: `extra_files: list[str] = field(default_factory=list)` (after `diff_path`, ~line 52)
- Add computed property:
  ```python
  @property
  def all_files(self) -> list[str]:
      files = []
      if self.diff_path:
          files.append(self.diff_path)
      files.extend(self.extra_files)
      return files
  ```

### 1b. AgentFilePanel — multi-file navigation

**File:** `src/sase/ace/tui/widgets/file_panel.py`

- Add instance state:
  - `_file_list: list[str] = []` — the ordered file list for the current agent
  - `_current_file_index: int = 0` — which file is currently displayed
- Add new public methods:
  - `set_file_list(files: list[str])` — store the file list, reset index to 0, display first file
  - `next_file()` — increment index (wrap around), display file at new index
  - `prev_file()` — decrement index (wrap around), display file at new index
  - `current_file_count() -> int` — return len of file list
  - `current_file_index() -> int` — return current index (0-based)
- The `display_static_file()` and `display_static_diff()` methods already work for individual files — the new cycling
  methods just call them with the appropriate path
- For running agents that use `update_display()` (live diffs), the live diff is always file index 0; static files (plan,
  etc.) are at index 1+

### 1c. AgentDetail — wire up file list

**File:** `src/sase/ace/tui/widgets/agent_detail.py`

- In `update_display()`, after determining which files the agent has, call `file_panel.set_file_list(agent.all_files)`
- For running agents: the live diff occupies slot 0 (still use `update_display(agent)` for it), extra static files at
  index 1+
- Add methods `cycle_next_file()` and `cycle_prev_file()` that delegate to file_panel
- Post a new message `FileListChanged(count, index)` when the file list or index changes (for indicator updates)

### 1d. FileVisibilityChanged update

**File:** `src/sase/ace/tui/widgets/file_panel.py`

- Extend `FileVisibilityChanged` to include `file_count: int` and `file_index: int` fields
- This allows the parent to know how many files exist for indicator display

---

## Phase 2: Keybindings + Visual Indicators (parallel with Phase 3)

**Depends on Phase 1. Independent of Phase 3.**

### 2a. Add ctrl+n / ctrl+p bindings to agents tab

**File:** `src/sase/ace/tui/app.py`

- Add bindings (around line 89-174 where existing bindings are):
  ```python
  Binding("ctrl+n", "next_agent_file", "Next file", show=False),
  Binding("ctrl+p", "prev_agent_file", "Prev file", show=False),
  ```
- Add action methods `action_next_agent_file()` and `action_prev_agent_file()` that:
  - Only activate when on the agents tab
  - Delegate to `agent_detail.cycle_next_file()` / `cycle_prev_file()`
- **Important**: ctrl+n/ctrl+p are already used in modals (base.py navigation, notification_modal.py file cycling,
  tag_input_modal.py). These modal bindings take priority when modals are open (Textual's focus system), so the new
  app-level bindings won't conflict.

### 2b. Update panel indicators

**File:** `src/sase/ace/tui/widgets/agent_detail.py`

- In `_update_panel_indicators()` (line 450), update the files indicator to show count:
  - Single file (or no extra files): `● files` (unchanged)
  - Multiple files: `● files [1/3]` (bold green when active, dim green when available but not active)
  - No files: `○ files` (unchanged)
- Track `_file_count` and `_file_index` from `FileVisibilityChanged` or `FileListChanged`

### 2c. Update help modal

**File:** `src/sase/ace/tui/modals/help_modal/bindings.py`

- Add ctrl+n / ctrl+p entries to `AGENTS_BINDINGS` (or the appropriate section) documenting "Next/Prev file in file
  panel"

---

## Phase 3: Plan File Saving + Agent Association (parallel with Phase 2)

**Depends on Phase 1. Independent of Phase 2.**

### 3a. Add project context to plan notification

**File:** `src/sase/main/plan_approve_handler.py`

- In `handle_plan_approve_command()`, add `project_dir` to the notification action_data:
  ```python
  project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
  ```
- Pass it through `notify_plan_approval()` → `action_data`

**File:** `src/sase/notifications/senders.py`

- Update `notify_plan_approval()` to accept and include `project_dir` in `action_data`

### 3b. Save plan to workspace on approval

**File:** `src/sase/ace/tui/actions/agents/_notification_actions.py`

- In `handle_plan_approval()`, in the `on_dismiss` callback when `result.action == "approve"`:
  1. Get `project_dir` from `notification.action_data`
  2. Resolve workspace_dir using `get_workspace_directory(project_basename, 1)` from `sase.running_field`
  3. Create `{workspace_dir}/.sase/plans/` directory
  4. Copy the plan file to `{workspace_dir}/.sase/plans/{plan_filename}`
  5. Include `saved_plan_path` in the `plan_response.json` response data

### 3c. Add .sase to .gitignore

**File:** `.gitignore`

- Add `.sase/` entry so the saved plans directory isn't tracked

### 3d. Thread plan path to done.json

**File:** `src/sase/axe_run_agent_runner.py`

- Before calling `execute_workflow()`, set `os.environ["SASE_ARTIFACTS_DIR"] = artifacts_dir`
- After `execute_workflow()` returns, check for `{artifacts_dir}/plan_path.json` and read `plan_path` from it
- Include `plan_path` in `done_marker` dict (alongside `diff_path`)
- Clean up the env var after

**File:** `src/sase/llm_provider/claude.py`

- After saving the plan (line ~136), write `{artifacts_dir}/plan_path.json`:
  ```python
  artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
  if artifacts_dir:
      plan_path_file = Path(artifacts_dir) / "plan_path.json"
      plan_path_file.write_text(json.dumps({"plan_path": str(saved_plan_path)}))
  ```

### 3e. Artifact loader reads plan_path

**File:** `src/sase/ace/tui/models/_loaders/_artifact_loaders.py`

- In `load_done_agents()` (around line 193-213), read `plan_path` from done.json data and set on Agent:
  ```python
  plan_path = data.get("plan_path")
  extra_files = [plan_path] if plan_path else []
  ```
  Pass `extra_files=extra_files` to the Agent constructor.

---

## Verification

### Phase 1 verification

- `just lint` passes (mypy + ruff)
- Manual: `sase ace --agent --keys tab` shows agents tab, agent entries still display correctly
- Verify `Agent.all_files` returns correct list for agents with diff_path, extra_files, or both

### Phase 2 verification

- `just lint` passes
- Manual: `sase ace --agent --keys tab` then check indicators show correct format
- Verify ctrl+n/ctrl+p don't break modal navigation (open help with `?`, use ctrl+n/ctrl+p to navigate)

### Phase 3 verification

- `just lint` passes
- Verify `.gitignore` includes `.sase/`
- End-to-end: trigger a plan approval flow and verify plan is saved to `{workspace_dir}/.sase/plans/`
- Verify done.json includes `plan_path` field after agent completion

### Cross-phase integration test

- After all phases: select an agent that had a plan approved → file panel should show both the diff and the plan file,
  navigable with ctrl+n/ctrl+p, with `● files [1/2]` indicator

## Key Files Summary

| File                                                       | Phase | Change                                          |
| ---------------------------------------------------------- | ----- | ----------------------------------------------- |
| `src/sase/ace/tui/models/agent.py`                         | 1     | Add `extra_files` field + `all_files` property  |
| `src/sase/ace/tui/widgets/file_panel.py`                   | 1     | Multi-file navigation (index tracking, cycling) |
| `src/sase/ace/tui/widgets/agent_detail.py`                 | 1, 2  | Wire cycling + update indicators                |
| `src/sase/ace/tui/app.py`                                  | 2     | ctrl+n/ctrl+p bindings                          |
| `src/sase/ace/tui/modals/help_modal/bindings.py`           | 2     | Document new bindings                           |
| `src/sase/main/plan_approve_handler.py`                    | 3     | Add project_dir to action_data                  |
| `src/sase/notifications/senders.py`                        | 3     | Accept project_dir param                        |
| `src/sase/ace/tui/actions/agents/_notification_actions.py` | 3     | Save plan to workspace on approve               |
| `src/sase/axe_run_agent_runner.py`                         | 3     | Set SASE_ARTIFACTS_DIR, read plan_path.json     |
| `src/sase/llm_provider/claude.py`                          | 3     | Write plan_path.json to artifacts               |
| `src/sase/ace/tui/models/_loaders/_artifact_loaders.py`    | 3     | Read plan_path → extra_files                    |
| `.gitignore`                                               | 3     | Add .sase/                                      |

## Parallelization

```
Phase 1 (foundation)
    ├──> Phase 2 (keybindings + indicators)
    └──> Phase 3 (plan saving + association)
```

Phase 2 and Phase 3 run in parallel after Phase 1 completes.
