---
create_time: 2026-03-22 22:50:38
status: done
bead_id: sase-8
prompt: sdd/prompts/202603/restructure_loose_files.md
---

# Plan: Restructure Loose Files in `src/sase/` (Option A)

## Goal

Move all 8 loose files out of the `src/sase/` package root into descriptively-named subpackages, following Option A from
`sdd/research/202603/loose_files_in_src_sase.md`.

## Target Structure

```
src/sase/
├── __init__.py
├── __main__.py
├── agent/                          # NEW — from 4 agent lifecycle files
│   ├── __init__.py                 # Re-exports public API
│   ├── launcher.py                 # ← agent_launcher.py
│   ├── names.py                    # ← agent_names.py
│   ├── multi_prompt.py             # ← multi_prompt.py
│   └── multi_prompt_launcher.py    # ← multi_prompt_launcher.py
├── sdd/                            # NEW — split from sdd.py
│   ├── __init__.py                 # Re-exports public API
│   ├── files.py                    # SDD file writing/committing
│   └── beads.py                    # Bead initialization
├── output.py                       # ← rich_utils.py (renamed)
├── core/                           # NEW — split from sase_utils.py
│   ├── __init__.py                 # Re-exports everything
│   ├── time.py                     # get_timezone, generate_timestamp
│   ├── paths.py                    # get_sase_directory, ensure_sase_directory,
│   │                               #   get_sase_tmpdir, shorten_path, make_safe_filename
│   ├── shell.py                    # run_shell_command, run_workspace_command,
│   │                               #   get_vendored_tool, strip_hook_prefix
│   └── changespec.py              # strip_reverted_suffix, changespec_name_to_branch,
│                                   #   changespec_name_to_branch_with_suffix, has_suffix,
│                                   #   get_next_suffix_number, get_workspace_directory_for_changespec
├── artifacts.py                    # ← shared_utils.py (workflow/artifacts half)
├── content.py                      # ← shared_utils.py (content helpers half)
└── ... (existing subpackages unchanged)
```

## Migration Strategy (applies to every phase)

Each phase follows the same pattern:

1. **Create** the new module(s) with the actual code
2. **Replace** the original file with a **re-export shim** — e.g.:
   ```python
   # sase_utils.py (backward-compat shim)
   from sase.core.time import get_timezone, generate_timestamp  # noqa: F401
   from sase.core.paths import get_sase_directory, ...          # noqa: F401
   ```
3. **Update all importers** in `src/` and `tests/` to use the new paths
4. **Check plugin repos** (`../sase-github`, `../retired Mercurial plugin`, `../sase-telegram`) for old imports — update if found
5. **Run `just check`** (fmt-check + lint + test) to verify nothing breaks

The shims remain until the final cleanup phase, protecting any external consumers we miss.

---

## Phase 1: Create `agent/` subpackage

**Scope**: Move the 4 agent lifecycle files into `src/sase/agent/`.

**Files to create**:

- `src/sase/agent/__init__.py` — re-exports all public names from the 4 modules
- `src/sase/agent/launcher.py` — code from `agent_launcher.py`
- `src/sase/agent/names.py` — code from `agent_names.py`
- `src/sase/agent/multi_prompt.py` — code from `multi_prompt.py`
- `src/sase/agent/multi_prompt_launcher.py` — code from `multi_prompt_launcher.py`

**Shims to leave behind** (4 files):

- `src/sase/agent_launcher.py` → re-exports from `sase.agent.launcher`
- `src/sase/agent_names.py` → re-exports from `sase.agent.names`
- `src/sase/multi_prompt.py` → re-exports from `sase.agent.multi_prompt`
- `src/sase/multi_prompt_launcher.py` → re-exports from `sase.agent.multi_prompt_launcher`

**Importers to update** (~30 import sites):

- `agent_launcher`: 4 external importers (axe/lumberjack, axe/cli, main/query_handler/\_daemon,
  ace/tui/actions/agent_workflow/\_agent_launch)
- `agent_names`: 5 external importers (xprompts/resume.yml, axe/run_agent_phases, ace/tui/actions/rename,
  xprompt/directives, scripts/sase_chop_wait_checks)
- `multi_prompt`: 8 external importers (agent_launcher, axe/run_agent_phases, main/xprompt_handler,
  main/query_handler/special_cases×2, main/query_handler/\_resume, main/query_handler/\_query,
  ace/tui/actions/agent_workflow/\_agent_launch×3)
- `multi_prompt_launcher`: 4 external importers (agent_launcher, axe/run_agent_phases,
  ace/tui/actions/agent_workflow/\_agent_launch, tests×3)
- Tests: test_agent_names.py, test_multi_prompt.py, test_multi_prompt_e2e.py, test_user_frontmatter.py,
  test_multi_prompt_launcher.py, test_xprompt_tags.py

**Internal cross-dependencies to fix**:

- `agent/launcher.py` imports from `sase.multi_prompt` and `sase.multi_prompt_launcher` → update to
  `sase.agent.multi_prompt` and `sase.agent.multi_prompt_launcher`
- `agent/multi_prompt_launcher.py` imports from `sase.agent_launcher` → update to `sase.agent.launcher`

**Estimated effort**: Low risk. Clear domain boundary. ~30 import sites.

---

## Phase 2: Create `sdd/` subpackage

**Scope**: Split `sdd.py` into two focused modules inside `src/sase/sdd/`.

**Files to create**:

- `src/sase/sdd/__init__.py` — re-exports all public names
- `src/sase/sdd/files.py` — SDD file operations: `write_sdd_files`, `commit_sdd_files`, `get_sdd_dir`,
  `update_spec_with_qa`, `expand_prompt_for_spec`, `_dry_expand_embedded_workflows`, `_get_primary_workspace_dir`
- `src/sase/sdd/beads.py` — bead initialization: `ensure_beads_initialized`, `_init_beads`

**Note**: Since `sdd.py` and `sdd/` can't coexist, **delete** the old `sdd.py` after creating the package. The
`sdd/__init__.py` re-exports everything so `from sase.sdd import X` still works — no shim needed.

**Importers to update** (~10 import sites):

- `src/sase/bead/cli.py` — imports from `sase.sdd`
- `src/sase/axe/run_agent_exec.py` — imports from `sase.sdd`
- `tests/test_sdd.py` — imports multiple functions
- `tests/test_epic_approval.py` — imports `ensure_beads_initialized`
- `tests/test_expand_for_spec.py` — imports `_dry_expand_embedded_workflows`, `expand_prompt_for_spec`

Since `__init__.py` re-exports everything, existing `from sase.sdd import X` imports will continue to work. But we
should still update them to point to the specific submodule for clarity (e.g.,
`from sase.sdd.files import write_sdd_files`).

**Estimated effort**: Low risk. Small file, few importers.

---

## Phase 3: Rename `rich_utils.py` → `output.py`

**Scope**: Rename the CLI formatting module to a more descriptive name.

**Files to create**:

- `src/sase/output.py` — full code from `rich_utils.py`

**Shim to leave behind**:

- `src/sase/rich_utils.py` → re-exports from `sase.output`

**Importers to update** (~23 import sites in src/, 1 test file):

- `shared_utils.py` (or by this point: `artifacts.py` if Phase 5 is done first — but phases are ordered, so this is
  still `shared_utils.py`)
- `xprompt/processor.py`, `xprompt/_jinja.py`
- `workflows/mentor.py`, `workflows/crs.py`, `workflows/rewind/workflow.py`, `workflows/utils.py`
- `workflows/accept/conflict_check.py`, `workflows/accept/workflow.py`, `workflows/amend.py`
- `workflows/commit/changespec_operations.py`, `workflows/commit/editor_utils.py`,
  `workflows/commit/project_file_utils.py`, `workflows/commit/workflow.py`
- `main/cl_handler.py`
- `gemini_wrapper/file_references.py`, `gemini_wrapper/wrapper.py`
- `llm_provider/_invoke.py`, `llm_provider/claude.py`, `llm_provider/codex.py`, `llm_provider/gemini.py`,
  `llm_provider/postprocessing.py`
- `tests/test_rich_utils.py` → rename to `tests/test_output.py`

**Estimated effort**: Medium risk due to 23 importers, but purely mechanical.

---

## Phase 4: Split `sase_utils.py` into `core/` subpackage

**Scope**: Break the God module (89 importers, 300 lines) into focused submodules.

**Files to create**:

- `src/sase/core/__init__.py` — re-exports everything for convenient `from sase.core import X`
- `src/sase/core/time.py` — `get_timezone` (32 importers), `generate_timestamp` (26 importers)
- `src/sase/core/paths.py` — `get_sase_directory` (4), `ensure_sase_directory` (8), `get_sase_tmpdir` (16),
  `shorten_path` (6), `make_safe_filename` (7)
- `src/sase/core/shell.py` — `run_shell_command` (2), `run_workspace_command` (2), `get_vendored_tool` (3),
  `strip_hook_prefix` (3)
- `src/sase/core/changespec.py` — `strip_reverted_suffix` (15), `changespec_name_to_branch` (2),
  `changespec_name_to_branch_with_suffix` (1), `has_suffix` (5), `get_next_suffix_number` (4),
  `get_workspace_directory_for_changespec` (3)

**Shim to leave behind**:

- `src/sase/sase_utils.py` → re-exports everything from `sase.core.*`

**Importers to update** (~89 import sites in src/, plus tests):

- This is the largest phase. All imports are of the form `from sase.sase_utils import X` and need to become
  `from sase.core.MODULE import X` (or `from sase.core import X`).
- Key test files: `tests/test_sase_utils.py` (rename to `tests/core/` or `tests/test_core_*.py`),
  `tests/test_hypothesis_property.py`, `tests/workflows/test_commit_duration.py`, several `tests/logs/` files,
  `tests/test_notification_models.py`, etc.

**Internal dependency**: `shared_utils.py` imports `get_timezone`, `run_shell_command`, and `get_vendored_tool` from
`sase_utils` — update these too.

**Estimated effort**: Highest risk phase due to volume (89+ import sites). But the work is mechanical — each import is a
simple path change. The shim ensures nothing breaks if we miss one.

---

## Phase 5: Split `shared_utils.py` into `artifacts.py` + `content.py`

**Scope**: Split the 28-importer utility module into two focused modules.

**Files to create**:

- `src/sase/artifacts.py` — workflow/artifacts functions:
  - `LANGGRAPH_RECURSION_LIMIT` constant
  - `WorkflowContext` dataclass
  - `convert_timestamp_to_artifacts_format`
  - `create_artifacts_directory`
  - `generate_workflow_tag`
  - `initialize_workflow`
  - `run_bam_command`
  - `get_sase_log_file`, `_initialize_log_file`, `_finalize_log_file`
  - `initialize_sase_log`, `finalize_sase_log`
- `src/sase/content.py` — content processing functions:
  - `dump_yaml` (+ `_LiteralBlockDumper`, `_str_literal_representer`)
  - `apply_section_marker_handling`
  - `content_ends_with_markdown_heading`
  - `ensure_str_content`

**Shim to leave behind**:

- `src/sase/shared_utils.py` → re-exports from `sase.artifacts` and `sase.content`

**Importers to update** (~28 import sites):

- `create_artifacts_directory` (9 sites) — most imported function
- `ensure_str_content` (6 sites)
- `dump_yaml` (5 sites)
- `convert_timestamp_to_artifacts_format` (4 sites)
- `apply_section_marker_handling` / `content_ends_with_markdown_heading` (3 sites each)
- `run_bam_command`, `generate_workflow_tag`, `initialize_sase_log`, `finalize_sase_log`, etc.
- Tests: `tests/test_shared_utils.py` → split into `tests/test_artifacts.py` + `tests/test_content.py`

**Estimated effort**: Medium risk. 28 importers, straightforward split.

---

## Phase 6: Remove backward-compat shims + final cleanup

**Scope**: Delete all re-export shim files and verify nothing depends on the old paths.

**Shims to remove**:

- `src/sase/agent_launcher.py`
- `src/sase/agent_names.py`
- `src/sase/multi_prompt.py`
- `src/sase/multi_prompt_launcher.py`
- `src/sase/rich_utils.py`
- `src/sase/sase_utils.py`
- `src/sase/shared_utils.py`

**Verification steps**:

1. Grep the entire repo for old import paths to confirm none remain
2. Grep plugin repos (`../sase-github`, `../retired Mercurial plugin`, `../sase-telegram`) for old import paths — update if found
3. Check `xprompts/` YAML files for any `from sase.old_module` references (e.g., `resume.yml` has inline Python)
4. Run `just check` in this repo
5. Run checks in plugin repos if they were modified

**Estimated effort**: Low risk if previous phases were thorough. This is just cleanup.

---

## Phase Summary

| Phase | What                          | Import sites | Risk   |
| ----- | ----------------------------- | ------------ | ------ |
| 1     | `agent/` subpackage           | ~30          | Low    |
| 2     | `sdd/` subpackage             | ~10          | Low    |
| 3     | `rich_utils.py` → `output.py` | ~24          | Medium |
| 4     | `sase_utils.py` → `core/`     | ~89          | High   |
| 5     | `shared_utils.py` → split     | ~28          | Medium |
| 6     | Remove all shims              | 0            | Low    |

**Total import sites to update**: ~181

## Notes for Each Claude Instance

- Always run `just install` before `just check` (workspace may have stale deps)
- Use `just fmt` to auto-format after edits, before running `just check`
- When updating imports, prefer `from sase.core.time import get_timezone` (specific) over
  `from sase.core import get_timezone` (via **init**)
- Local/deferred imports (inside function bodies) need updating too — grep carefully
- The xprompts/\*.yml files can contain inline Python with imports — check those too
