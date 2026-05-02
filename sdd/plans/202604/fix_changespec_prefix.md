---
status: done
create_time: 2026-04-03
---

# Fix: Enforce project prefix on ChangeSpec names

## Problem

Codex (and potentially other agents) sometimes create ChangeSpecs without the required `<project>_` prefix in their
names. For example, `fix_split_1` instead of `sase_fix_split_1`.

## Root Cause

The system currently relies on the commit stop hook **instructing** the agent to include the project prefix in the
`"name"` field of the commit payload (`_build_name_instruction` in `sase_commit_stop_hook.py`). But this is a soft
instruction — agents (especially Codex) may ignore it and pass the raw `SASE_PR_NAME` value (e.g., `"fix_split"`)
without the prefix.

The code path has no enforcement:

1. `CommitWorkflow.run()` gets `base_name` from `self._payload["name"]` (whatever the agent passed)
2. `compute_suffixed_cl_name(project_name, base_name)` adds `_<N>` suffix but does NOT verify or add the project prefix
3. `create_changespec_for_workflow(..., cl_name=base_name)` only adds the prefix via `_derive_cl_name()` when
   `cl_name is None` — when it's explicitly provided, it's used as-is

## Fix

Add a normalization helper `ensure_project_prefix(project_name, cl_name)` and apply it at two choke points:

1. **`compute_suffixed_cl_name()`** in `changespec_operations.py` — normalizes before computing the suffix and writing
   the reservation
2. **`create_changespec_for_workflow()`** in `workspace_provider/changespec.py` — normalizes when `cl_name` is
   explicitly provided (defense-in-depth)

The helper simply checks if `cl_name` already starts with `{project_name}_` and prepends it if not. It should live in
`core/changespec.py` alongside the other name utilities.

## Phases

### Phase 1: Add `ensure_project_prefix` helper

- Add `ensure_project_prefix(project_name: str, cl_name: str) -> str` to `src/sase/core/changespec.py`
- Logic: if `cl_name` already starts with `f"{project_name}_"`, return as-is; otherwise return
  `f"{project_name}_{cl_name}"`
- Add unit tests

### Phase 2: Apply normalization at choke points

- In `compute_suffixed_cl_name()` (`changespec_operations.py`): normalize `cl_name` before suffix computation
- In `create_changespec_for_workflow()` (`workspace_provider/changespec.py`): normalize when `cl_name is not None`
- Add tests verifying the prefix is present in the resulting ChangeSpec name
