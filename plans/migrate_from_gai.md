# Plan: Sync SASE Codebase to Match GAI Exactly

## Context

The `sase` project (`/Users/bbugyi/projects/github/bbugyi200/sase`) was migrated from the `gai` codebase
(`~/.local/share/chezmoi/home/lib/gai/`), but an older snapshot of GAI was used. Additionally, during migration, extra
files and features were added to SASE that don't exist in GAI (YAML ChangeSpec support, loop system, split workflows,
etc.). The goal is to make SASE's code match GAI exactly, removing all SASE-only additions.

## Scope Summary

| Category                                  | Count | Action             |
| ----------------------------------------- | ----- | ------------------ |
| Common src files (with content diffs)     | 152   | Overwrite from GAI |
| Common src files (import-path-only diffs) | 45    | Overwrite from GAI |
| Common src files (identical)              | 85    | No change needed   |
| SASE-only src files                       | 52    | **Delete**         |
| Common test files (with diffs)            | 168   | Overwrite from GAI |
| SASE-only test files                      | 19    | **Delete**         |
| GAI-only test files                       | 3     | **Add**            |
| xprompts (changed)                        | 8     | Overwrite from GAI |
| xprompts (SASE-only)                      | 2     | **Delete**         |
| docs (changed)                            | 6     | Overwrite from GAI |

## Conversion Strategy

A Python conversion script will handle the bulk work. For each GAI file, it will:

1. **Rename identifiers**: `gai` -> `sase`, `Gai` -> `Sase`, `GAI` -> `SASE`
2. **Rename compound identifiers**: `gai_utils` -> `sase_utils`, `gai_get_workspace` -> `sase_get_workspace`,
   `gaiproject.vim` -> `saseproject.vim`
3. **Rename paths**: `~/.gai/` -> `~/.sase/`, `~/.config/gai/` -> `~/.config/sase/`
4. **Add import prefixes**: `from ace.xxx` -> `from sase.ace.xxx` (all first-party bare imports get `sase.` prefix)
5. **Write to SASE location**: `gai/src/foo.py` -> `sase/src/sase/foo.py`

The `I` (isort) rule will be removed from ruff config so import ordering matches GAI.

### Files needing manual structural fixes after conversion (~3-5 files)

- `src/sase/xprompt/loader.py`: `get_sase_package_xprompts_dir()` needs 4 parent traversals (not 2) due to
  `src/sase/xprompt/` depth
- `src/sase/__main__.py`: docstring wording slightly different (minor)
- `tests/conftest.py`: GAI version has `sys.path.insert` hacks that SASE doesn't need (uses proper packaging) - keep
  SASE's version, just update fixture/import content to match GAI

---

## Phase 1: Ruff Config + Conversion Script + Source File Sync

**Goal**: Overwrite all 282 common src files from GAI, delete 52 SASE-only files, verify lint passes.

### Step 1.1: Adjust ruff config

- **File**: `pyproject.toml`
- Remove `"I"` (isort) from `[tool.ruff.lint] select` list
- This preserves GAI's import ordering style

### Step 1.2: Write conversion script

- **File**: `scripts/sync_from_gai.py` (temporary, delete after use)
- Input: GAI file path, output: converted SASE content
- Handles all gai->sase renaming patterns listed above
- Handles import prefix addition for all known first-party modules: `ace`, `axe`, `xprompt`, `llm_provider`,
  `vcs_provider`, `gemini_wrapper`, `commit_workflow`, `commit_utils`, `accept_workflow`, `rewind_workflow`,
  `status_state_machine`, `running_field`, `sase_utils`, `shared_utils`, `workflow_utils`, `workflow_base`,
  `rich_utils`, `change_actions`, `chat_history`, `command_history`, `hook_history`, `prompt_history`, `renumber_utils`,
  `mentor_config`, `metahook_config`, `axe_config`, `summarize_utils`, `summarize_workflow`, `crs_workflow`,
  `mentor_workflow`, `amend_workflow`, `axe_runner_utils`, `axe_crs_runner`, `axe_fix_hook_runner`, `axe_mentor_runner`,
  `axe_run_agent_runner`, `axe_run_workflow_runner`, `axe_summarize_hook_runner`, `split_spec`, `snippet_config`,
  `fix_hook_workflow`, `loop_runner_utils`, `loop_crs_runner`, `loop_fix_hook_runner`, `loop_mentor_runner`,
  `loop_run_agent_runner`, `loop_summarize_hook_runner`

### Step 1.3: Run conversion on all src files

- For each of the 282 common files in GAI `src/`, convert and write to SASE `src/sase/`
- Special case: `gai_utils.py` -> already exists as `sase_utils.py`

### Step 1.4: Delete 52 SASE-only src files

```
src/sase/__init__.py  (the __init__.py with version - GAI doesn't have this)
src/sase/ace/changespec/project_spec.py
src/sase/ace/changespec/structured_updates.py
src/sase/ace/handlers/tool_handlers.py
src/sase/ace/hooks/queries.py
src/sase/ace/loop/ (entire directory - 14 files)
src/sase/ace/split_workflow/ (entire directory - 5 files)
src/sase/ace/tui/actions/agent_workflow_launch.py
src/sase/ace/tui/actions/agent_workflow.py
src/sase/ace/tui/actions/agents.py
src/sase/ace/tui/actions/agents/_revival.py
src/sase/ace/tui/actions/hints.py
src/sase/ace/tui/actions/navigation.py
src/sase/ace/tui/modals/bug_input_modal.py
src/sase/ace/tui/modals/chat_select_modal.py
src/sase/ace/tui/modals/cl_name_input_modal.py
src/sase/ace/tui/modals/help_modal.py
src/sase/ace/tui/modals/snippet_select_modal.py
src/sase/ace/tui/models/_loaders.py
src/sase/ace/tui/widgets/diff_panel.py
src/sase/ace/tui/widgets/saved_queries_panel.py
src/sase/fix_hook_workflow.py
src/sase/gemini_wrapper/snippet_processor.py
src/sase/loop_crs_runner.py
src/sase/loop_fix_hook_runner.py
src/sase/loop_mentor_runner.py
src/sase/loop_run_agent_runner.py
src/sase/loop_runner_utils.py
src/sase/loop_summarize_hook_runner.py
src/sase/main/query_handler/workflows.py
src/sase/sase_utils.py  (will be regenerated from gai_utils.py)
src/sase/snippet_config.py
src/sase/split_spec.py
src/sase/xprompt/output_processing.py
src/sase/xprompt/output_schema.py
src/sase/xprompt/validators.py
```

**Note**: `src/sase/__init__.py` needs special handling - GAI doesn't have one, but SASE needs it for the package. Keep
it but verify content.

### Step 1.5: Fix structural files

- `src/sase/xprompt/loader.py`: Fix `get_sase_package_xprompts_dir()` path traversal

### Step 1.6: Verify

- Run `just lint` (ruff check + mypy)
- Fix any import errors or issues

---

## Phase 2: Test File Sync

**Goal**: Sync all test files from GAI to SASE, delete extras, add missing.

### Step 2.1: Run conversion on all common test files

- Apply conversion script to 168 common test files
- GAI tests use bare imports (`from ace.xxx`), convert to `from sase.ace.xxx`

### Step 2.2: Handle conftest.py specially

- GAI's `conftest.py` has `sys.path.insert` hacks that SASE doesn't need
- Copy GAI's conftest content (fixtures, etc.) but remove the `sys.path` hack
- Keep SASE's import style (`from sase.xxx`)

### Step 2.3: Add 3 missing test files from GAI

- `test_ace_tui_app.py`
- `test_gai_utils.py` -> `test_sase_utils.py` (rename)
- `test_hooks_reset_dollar.py`

### Step 2.4: Delete 19 SASE-only test files

```
test_ace_tui_keybinding_footer.py
test_clipboard.py
test_diff_panel_static_file.py
test_fix_hook_workflow.py
test_hooks_queries.py
test_loop_runner_utils.py
test_mentor_config_xprompt.py
test_mentor_config.py
test_parser_dispatch.py
test_project_spec.py
test_sase_utils.py  (will be regenerated from test_gai_utils.py)
test_split_spec.py
test_standalone_steps.py
test_status_state_machine.py
test_structured_updates.py
test_vcs_provider_git.py
test_workflow_executor_control_flow.py
test_workflow_validator.py
test_xprompt_loader.py
```

### Step 2.5: Verify

- Run `just test`
- Fix test failures

---

## Phase 3: Non-Python Files + Full Verification

**Goal**: Sync xprompts, docs, and other non-Python files. Run full check suite.

### Step 3.1: Sync xprompts (8 changed files)

- Apply gai->sase conversion to: `amend.yml`, `commit.yml`, `file.yml`, `json.yml`, `propose.yml`, `split_executor.md`,
  `split.yml`, `workflow.schema.json`
- Delete 2 SASE-only: `project_spec.schema.json`, `test_workflow.yml`

### Step 3.2: Sync docs (6 changed files)

- Apply gai->sase conversion to: `llms.md`, `project_spec.md`, `vcs_llms_problems_critique.md`, `vcs_llms_problems.md`,
  `vcs.md`, `workflow_spec.md`

### Step 3.3: Sync other non-Python files

- Compare and sync `src/sase/ace/CLAUDE.md`
- Compare and sync `src/sase/ace/README.md`
- `styles.tcss` is already identical

### Step 3.4: Full verification

- Run `just check` (fmt-check + lint + test)
- Fix any remaining issues
- Clean up temporary conversion script

### Step 3.5: Final diff audit

- Run the comparison script one more time to verify zero content diffs remain
- Ensure no SASE-only files remain that shouldn't be there

---

## Recent Commits (6b8ceeec, 5ffc6e40)

These commits fixed migration issues (70 xfail tests, 30 mypy errors) in the current SASE code. Since our plan
overwrites all src/test files from GAI, these fixes become irrelevant - they'll be replaced by the correct GAI code.
Noteworthy items:

- **`pyproject.toml`**: Added `pytest-asyncio` dep and `asyncio_mode = "auto"` - keep these (they're SASE
  infrastructure, not code sync)
- **`bin/executable_sase_commit_workflow`**: Created for a test fix - delete this since GAI doesn't have it (GAI's
  test_commit_workflow.py will be synced and may need a different approach)

---

## Key Decisions

- **Ruff `I` rule**: Remove to preserve GAI's import ordering
- **conftest.py**: Merge GAI fixtures into SASE's packaging-friendly structure
- **`__init__.py`**: Keep SASE's package `__init__.py` (GAI doesn't have one)
- **Formatting**: Copy GAI code as-is (with gai->sase rename), don't re-apply formatting rules that alter GAI's style
- **`bin/executable_sase_commit_workflow`**: Delete (not from GAI)
