---
create_time: 2026-04-03 12:41:57
status: done
---

# Plan: Fix `sase run "#hg:... #split"` cl_name regression when `hg` workflow is not locally registered

## Problem Summary

`#split` setup fails because `retired_mercurial_plugin_update` is called with `cl_name="sase"` instead of the expected Mercurial ref
(for example, `yserve_batch_create_update`).

Observed runtime evidence:

- Workflow inputs show `cl_name="sase"`.
- Failing command is `retired_mercurial_plugin_update sase`.
- Query was `#hg:yserve_batch_create_update #split`.

## Root Cause

The current `_resolve_vcs_cwd()` logic only attempts VCS-ref extraction for prefixes returned by `get_workflow_names()`.
In environments where the local registry does not include `hg` (for example, only `gh`/`git` are installed), the
`#hg:...` token is never matched.

That causes `_resolve_vcs_cwd()` to return `None`, so `run_query()` falls back to deriving `cl_name` from the project
file directory (here, `sase`).

This means the previous `vcs_ref -> cl_name` fix is effectively bypassed for unregistered VCS prefixes, even though the
raw ref is present in the prompt.

## Design Goals

1. Always derive `cl_name` from the raw `#type:ref` token when present, independent of local provider registration.
2. Preserve existing behavior of changing CWD when a registered provider can resolve the ref.
3. Avoid introducing runtime-specific branching; keep provider behavior uniform and plugin-driven.
4. Cover the regression with tests that do not require `hg` plugin installation.

## Proposed Changes

### 1) Make `_resolve_vcs_cwd()` parse the first generic `#type:ref` token

- Add a generic parser path that extracts `(workflow_type, ref)` from normalized query text using a provider-agnostic
  regex.
- Return `(project_name, ref)` even when `workflow_type` is not in `get_workflow_names()` or `resolve_ref()` fails.
- Attempt `resolve_ref()` + `os.chdir()` only when the extracted type is actually registered.
- Keep cache-clear behavior (`detect_project.cache_clear()`) only when chdir occurs.

Net effect:

- `run_query()` always receives `vcs_ref` for `cl_name` when a VCS token exists.
- Workspace CWD switching remains best-effort and plugin-dependent.

### 2) Keep `run_query()` cl_name resolution as-is

Current logic already prefers returned `vcs_ref` and only falls back when absent. With change (1), no additional
run_query logic changes are required beyond any type/variable adjustments needed by refactor.

### 3) Add/adjust tests

In `tests/test_xprompt_processor_workflow.py`:

- Add a regression test where `get_workflow_names()` does not include `hg`, input is
  `#hg:yserve_batch_create_update #split`, and `_resolve_vcs_cwd()` still returns `(ref, ref)` with no `chdir` call.
- Keep existing tests validating registered-workflow resolution behavior.

This ensures behavior is stable across environments with different installed workspace plugins.

## Verification Plan

1. Run targeted tests for `_resolve_vcs_cwd` behavior.
2. Run full repo checks (`just install` first if needed, then `just check`) as required by repo instructions.
3. Confirm no additional runtime/provider regressions in affected parsing path.

## Risks and Mitigations

- Risk: Generic regex could capture non-VCS xprompt syntax.
  - Mitigation: Anchor to `#type:ref` shape with explicit allowed chars and only return when matched; preserve
    normalization step.
- Risk: Changing return behavior might alter callers expecting `None` for unresolved refs.
  - Mitigation: Scope analysis confirms only `run_query()` consumes this helper for `cl_name`/project context, where
    fallback-to-ref is desired.
