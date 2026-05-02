---
create_time: 2026-03-21 01:17:04
status: done
prompt: sdd/prompts/202603/config_grouping.md
---

# Plan: sase-6.5 — Config grouping + final loose file cleanup

## Goal

Move 3 config files (`config.py`, `mentor_config.py`, `metahook_config.py`) into a new `config/` package under
`src/sase/`. Update all imports. Move test files. Pass `just check`.

## File Moves

| From                          | To                            |
| ----------------------------- | ----------------------------- |
| `src/sase/config.py`          | `src/sase/config/core.py`     |
| `src/sase/mentor_config.py`   | `src/sase/config/mentor.py`   |
| `src/sase/metahook_config.py` | `src/sase/config/metahook.py` |

Create `src/sase/config/__init__.py` that re-exports all public symbols from the three modules, so that existing
`from sase.config import X` continues to work (pointing to the `config/` package `__init__.py`).

## Re-export strategy

`config/__init__.py` will re-export the public API from `config.core`:

- `CONFIG_DIR`, `CHEZMOI_HOME`, `get_use_chezmoi`, `load_merged_config`, `load_xprompts_by_source`

This means all 13 src/ import sites using `from sase.config import ...` will **just work** with no changes needed, since
`from sase.config import X` will now resolve to the package's `__init__.py`.

For `mentor_config` and `metahook_config`, imports change to `from sase.config.mentor import ...` and
`from sase.config.metahook import ...`.

## Import Updates Required

### mentor_config → config.mentor (~14 sites)

**src/ files (7 sites):**

1. `src/sase/workflows/mentor.py` — `from sase.mentor_config import ...`
2. `src/sase/ace/display_helpers.py` — lazy import inside function
3. `src/sase/ace/mentors.py` — two lazy imports inside functions
4. `src/sase/ace/scheduler/mentor_profile_matching.py` — top-level import
5. `src/sase/ace/scheduler/mentor_checks.py` — top-level import
6. `src/sase/ace/scheduler/mentor_runner.py` — top-level import

**tests/ files (7 sites):**

1. `tests/test_mentor_checks.py` — multiple imports (top-level + inside functions)
2. `tests/test_mentors_wip.py`
3. `tests/test_mentor_config_prompt.py`
4. `tests/test_mentor_config_loading.py`
5. `tests/test_mentor_config_retrieval.py`
6. `tests/test_mentor_config_dataclass.py`

### metahook_config → config.metahook (~3 sites)

**src/ files (2 sites):**

1. `src/sase/ace/hooks/execution.py` — lazy import inside function
2. `src/sase/axe/summarize_hook_runner.py` — top-level import

**tests/ files (1 site):**

1. `tests/test_metahook_config.py`

### config → config (0 changes needed due to re-exports)

No import changes needed — `from sase.config import X` still works because the package `__init__.py` re-exports
everything.

**One internal fix**: `config/mentor.py` and `config/metahook.py` both import
`from sase.config import load_merged_config`. This will now be an intra-package import: change to
`from sase.config.core import load_merged_config` (or use relative import `from .core import load_merged_config`).

## Test File Moves

No test files need to be moved/renamed. The test files (`tests/test_config.py`, `tests/test_mentor_config_*.py`,
`tests/test_metahook_config.py`) test the public API, not the file locations. They just need import updates.

## Steps

1. Run `just install` to ensure env is current
2. Create `src/sase/config/` directory and `__init__.py`
3. `git mv` the 3 source files to their new locations
4. Write `config/__init__.py` with re-exports from `.core`
5. Fix intra-package imports in `config/mentor.py` and `config/metahook.py`
6. Update all `from sase.mentor_config` → `from sase.config.mentor` imports
7. Update all `from sase.metahook_config` → `from sase.config.metahook` imports
8. Run `just check` to validate
