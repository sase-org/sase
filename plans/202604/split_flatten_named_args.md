---
create_time: 2026-04-03 12:08:43
status: done
---

# Fix dropped implicit args when flattening anonymous workflow refs

## Problem Summary

`$ sase run "#hg:<cl> #split"` can fail with `jinja2.exceptions.UndefinedError: 'cl_name' is undefined` in workflow step
templates that require `{{ cl_name }}`.

Evidence from the provided logpack (`~/tmp/260403_115422`) shows:

- Failing run artifact (`artifacts/sase/artifacts/run/20260403115359/workflow_state.json`) has `context` containing only
  `split_desc` and `chain`.
- Successful direct split artifact (`artifacts/yserve/artifacts/workflow-split/20260403115337/workflow_state.json`)
  contains `cl_name`, `project_file`, and `workspace_num` in `context`.

This indicates implicit args are present before execution in some paths but are dropped in the `sase run` anonymous
wrapper path.

## Root Cause Hypothesis

In `execute_workflow()`, `_flatten_anonymous_workflow()` may return a `(workflow, positional_args, named_args)` tuple
parsed from the embedded reference (e.g., `#split(...)`).

Current behavior overwrites the caller-provided `named_args` entirely with flatten-derived args, which strips implicit
context injected by `run_query()`.

As a result, workflows expecting `cl_name` in their template context fail at the first script step.

## Implementation Plan

1. Preserve caller-level named args during flattening.

- In `src/sase/xprompt/workflow_runner.py`, keep the original `named_args` from `execute_workflow()`.
- After flattening, merge flattened named args with the original map instead of replacing it.
- Precedence rule:
  - Keep explicit flattened args for workflow inputs (user-provided args in `#name(...)`).
  - Preserve implicit caller context keys (e.g., `cl_name`, `project_file`, `workspace_num`) when not explicitly set by
    flattening.
- Ensure wrapper-level model override injection (`__sase_workflow_model_override`) still works.

2. Add regression tests.

- Add/extend tests in workflow runner tests to cover:
  - `execute_workflow()` with anonymous prompt wrapping `#split`-style workflow and caller-provided `named_args`
    containing implicit context.
  - Verify final executor args/context still include `cl_name` (and related keys) after flattening.
  - Verify explicit args parsed from `#workflow(...)` still override caller defaults where intended.

3. Validate behavior end-to-end in repo checks.

- Run `just install` (workspace requirement).
- Run targeted tests for workflow flattening / runner paths.
- Run `just check` before finishing (required by repo instructions).

## Risks / Edge Cases

- Over-merging could leak wrapper-only keys into unrelated workflows; mitigate by using simple dictionary merge with
  clear precedence and existing arg-processing path.
- Must avoid breaking existing behavior where flatten-parsed args intentionally override defaults.
- Keep runtime parity: fix in shared code path, no runtime-specific branching.

## Expected Outcome

`$ sase run "#hg:<cl> #split"` and similar anonymous-wrapper invocations preserve implicit workflow context so templates
that reference `{{ cl_name }}` no longer fail due to missing variables.
