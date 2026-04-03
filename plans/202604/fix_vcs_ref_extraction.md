---
create_time: 2026-04-03 12:43:40
status: done
---

# Plan: Fix `cl_name` still "sase" when `resolve_ref` fails

## Problem

Running `sase run "#hg:yserve_batch_create_update #split"` still produces `cl_name="sase"` despite the previous fix
(commit 64ca326d). The `sase_split_setup` script fails because it runs `sase_google_update sase` instead of
`sase_google_update yserve_batch_create_update`.

## Root Cause

`_resolve_vcs_cwd()` in `_query.py` only returns `(project_name, vcs_ref)` inside the success path — when
`resolve_ref()` succeeds AND `resolved.primary_workspace_dir` exists (line 51-57). If `resolve_ref()` throws an
exception, the function `continue`s past that workflow type and ultimately returns `None`, losing the `vcs_ref`
entirely.

The caller then falls through to `cl_name = os.path.basename(os.path.dirname(project_file))` which gives "sase" (the
current project directory name).

The VCS ref "yserve_batch_create_update" is always extractable from the query text via regex — it does not depend on
workspace resolution succeeding. The previous plan explicitly stated this but the implementation didn't separate the two
concerns.

## Fix

### Separate ref extraction from workspace resolution

**File:** `src/sase/main/query_handler/_query.py`

Restructure `_resolve_vcs_cwd()` so that:

1. It extracts the raw `vcs_ref` from the query pattern FIRST (pure regex, no resolution needed)
2. It THEN attempts `resolve_ref()` for CWD resolution (best-effort — failure is OK)
3. It returns the `vcs_ref` regardless of whether resolution succeeded

Concretely, change the return to happen after the loop body attempts resolution but before giving up on the ref. If
resolution fails (exception or no workspace dir), still return `(None, ref)` so the caller gets the ref for `cl_name`.

### Update tests

Add a test covering the case where `resolve_ref()` raises an exception, verifying that `_resolve_vcs_cwd` still returns
the extracted `vcs_ref`.

## Scope

- **One file changed:** `_query.py` (restructure `_resolve_vcs_cwd`)
- **One test file updated:** `test_xprompt_processor_workflow.py` (new test case)
