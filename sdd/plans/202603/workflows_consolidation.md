---
create_time: 2026-03-21 00:48:36
status: wip
prompt: sdd/prompts/202603/workflows_consolidation.md
---

# Plan: sase-6.3 — Consolidate workflows under workflows/

## Summary

Move 5 loose workflow files, 4 workflow packages, and renumber_utils.py into a new `workflows/` package under
`src/sase/`. Update all imports across the codebase (src, tests, xprompts, scripts). Follow the same patterns
established in Phase 1 (sase-6.1) and Phase 2 (sase-6.2): use git mv, direct import rewriting (no re-exports), empty
`__init__.py` for the new package.

## Files to Move

### Loose files → workflows/

| From                 | To                            |
| -------------------- | ----------------------------- |
| `workflow_base.py`   | `workflows/base.py`           |
| `workflow_utils.py`  | `workflows/utils.py`          |
| `amend_workflow.py`  | `workflows/amend.py`          |
| `crs_workflow.py`    | `workflows/crs.py`            |
| `mentor_workflow.py` | `workflows/mentor.py`         |
| `renumber_utils.py`  | `workflows/renumber_utils.py` |

### Packages → workflows/

| From               | To                        |
| ------------------ | ------------------------- |
| `commit_workflow/` | `workflows/commit/`       |
| `accept_workflow/` | `workflows/accept/`       |
| `rewind_workflow/` | `workflows/rewind/`       |
| `commit_utils/`    | `workflows/commit_utils/` |

## Steps

### Step 1: Create workflows/ package and move files

```bash
mkdir -p src/sase/workflows
touch src/sase/workflows/__init__.py  # empty, per prior phases
```

Use `git mv` for all moves:

- 6 loose files into workflows/ with new names
- 4 directories into workflows/

### Step 2: Update imports in moved files (internal cross-references)

All moved files that reference other moved modules need updating:

- `from sase.workflow_base` → `from sase.workflows.base`
- `from sase.workflow_utils` → `from sase.workflows.utils`
- `from sase.commit_utils` → `from sase.workflows.commit_utils`
- `from sase.commit_utils.entries` → `from sase.workflows.commit_utils.entries` (etc.)
- `from sase.renumber_utils` → `from sase.workflows.renumber_utils`
- `from sase.commit_workflow` → `from sase.workflows.commit`
- `from sase.accept_workflow` → `from sase.workflows.accept`
- `from sase.rewind_workflow` → `from sase.workflows.rewind`

### Step 3: Update imports in non-moved files

Key import sites (by module, approximate counts):

- `commit_utils`: ~22 files in src/ and tests/
- `workflow_utils`: ~16 files in src/ and tests/
- `workflow_base`: 5 files
- `accept_workflow`: 7 files
- `renumber_utils`: 5 files (3 tests + 2 src)
- `commit_workflow`: 1 file
- `rewind_workflow`: 1 file
- `amend_workflow`: 1 file
- `crs_workflow`: 3 files
- `mentor_workflow`: 1 file

### Step 4: Update xprompts and scripts

- `src/sase/xprompts/gchange.yml`: references `from sase.workflow_utils`
- `src/sase/scripts/sase_commit_workflow`: references `from sase.commit_utils`, `from sase.workflow_utils`

### Step 5: Move test files

Test files to move into `tests/workflows/` (creating the directory):

- `tests/test_workflow_utils.py` → `tests/workflows/test_utils.py`
- `tests/test_renumber_utils.py` → `tests/workflows/test_renumber_utils.py`
- `tests/test_renumber_utils_snapshot.py` → `tests/workflows/test_renumber_utils_snapshot.py`
- `tests/test_renumber_entries.py` → `tests/workflows/test_renumber_entries.py`
- `tests/test_parsing.py` → `tests/workflows/test_parsing.py`
- `tests/test_conflict_check.py` → `tests/workflows/test_conflict_check.py`
- `tests/test_commit_workflow.py` → `tests/workflows/test_commit_workflow.py`
- `tests/test_commit_add.py` → `tests/workflows/test_commit_add.py`
- `tests/test_commit_duration.py` → `tests/workflows/test_commit_duration.py`
- `tests/test_commit_utils_modifiers.py` → `tests/workflows/test_commit_utils_modifiers.py`
- `tests/test_new_workflows.py` → `tests/workflows/test_new_workflows.py`

Update imports within all moved and non-moved test files.

### Step 6: Validate

Run `just install && just check` to ensure fmt, lint, and tests all pass.
