---
create_time: 2026-04-17 18:31:05
status: wip
prompt: sdd/prompts/202604/xprompts_enabled_markers_stripped_in_early_phase.md
---

# Plan: Preserve `%xprompts_enabled` markers through `preprocess_prompt_early`

## Problem

Running `sase ace` and accepting mentor-review comments produces a file-validation error for `@` tokens that live inside
a `%xprompts_enabled:false`/`%xprompts_enabled:true` region:

```
❌ ERROR: The following file(s) referenced in the prompt do not exist:
  - @Input
  - @visibleForTemplate

⚠️ File validation failed. Terminating workflow to prevent errors.
```

The mentor-review xprompt (`src/sase/xprompts/make_mentor_changes.yml:24-32`) correctly wraps the rendered change
descriptions in disabled-region markers:

```yaml
- name: apply
  prompt_part: |
    #{{ vcs_type }}:{{ cl_name }}

    Apply the following code review changes to the codebase. Make each change as described,
    run any relevant tests, and commit your changes.

    %xprompts_enabled:false
    {{ render_changes.rendered_changes }}
    %xprompts_enabled:true
```

The failing `@Input` and `@visibleForTemplate` tokens appear INSIDE that wrapping (they are Dart/Angular annotations
quoted inside change descriptions), so `validate_file_references` should never observe them.

## Root cause

`preprocess_prompt_early` in `src/sase/llm_provider/preprocessing.py:99` calls `extract_prompt_directives(prompt)`.
Inside `extract_prompt_directives` (`src/sase/xprompt/directives.py:305`), after parsing directives the function calls
`strip_disabled_region_markers(cleaned)` at three return sites: lines 336, 394, and 509.

So after `preprocess_prompt_early` finishes, the `%xprompts_enabled:false/true` markers are GONE. Then
`preprocess_prompt_late` (same module, line 104) runs:

1. Line 141: `protect_disabled_regions(prompt, disabled_regions)` — finds no markers, protects nothing.
2. Line 154: `validate_file_references(prompt)` — sees `@Input` etc. exposed, errors out and terminates.

The bug is only visible through the two-phase pipeline (early → late) which is exactly the path used by
`_execute_prompt_step` in `src/sase/xprompt/workflow_executor_steps_prompt.py:184,217`.

The existing regression test
`tests/test_disabled_regions.py::TestPreprocessPromptLateDisabledRegions::test_validate_mode_ignores_at_refs_in_disabled_region_inline_close`
calls `preprocess_prompt_late` DIRECTLY on a prompt that still has markers, so it did not catch this failure mode.

The marker stripping inside `extract_prompt_directives` was added in commit `8b416cc6` (fix: Respect model picker
selection for coder agents). The PROTECTION that commit added (to prevent re-parsing `%model` inside `#resume`
expansions) is correct and must stay. Only the final `strip_disabled_region_markers` call is premature for the two-phase
preprocessing pipeline.

## Fix

### Step 1 — `src/sase/xprompt/directives.py`

Add a `strip_disabled_markers: bool = True` keyword-only parameter to `extract_prompt_directives`. Guard the three
`strip_disabled_region_markers(...)` call sites on this flag. Default stays `True` so every existing caller and the unit
test `test_disabled_region_markers_stripped_from_output` keeps passing.

```python
def extract_prompt_directives(
    prompt: str, *, strip_disabled_markers: bool = True
) -> tuple[str, PromptDirectives]:
    ...
    if not matches:
        prompt = unprotect_disabled_regions(prompt, disabled_regions)
        if strip_disabled_markers:
            prompt = strip_disabled_region_markers(prompt)
        return unprotect_fenced_blocks(prompt, fenced_blocks), PromptDirectives()
    ...
    if not regions_to_remove:
        prompt = unprotect_disabled_regions(prompt, disabled_regions)
        if strip_disabled_markers:
            prompt = strip_disabled_region_markers(prompt)
        return unprotect_fenced_blocks(prompt, fenced_blocks), PromptDirectives()
    ...
    cleaned = unprotect_disabled_regions(cleaned, disabled_regions)
    if strip_disabled_markers:
        cleaned = strip_disabled_region_markers(cleaned)
    ...
```

### Step 2 — `src/sase/llm_provider/preprocessing.py`

In `preprocess_prompt_early`, pass `strip_disabled_markers=False`:

```python
prompt, directives = extract_prompt_directives(prompt, strip_disabled_markers=False)
```

The final `strip_disabled_region_markers(prompt)` in `preprocess_prompt_late` (line 171) continues to strip markers at
the end of the full pipeline, so observable downstream output is unchanged for the full pipeline.

### Step 3 — tests

**`tests/test_directives_extract.py`** — add a unit test that calls
`extract_prompt_directives(prompt, strip_disabled_markers=False)` and asserts that `%xprompts_enabled:false` and
`%xprompts_enabled:true` are still present in the returned cleaned prompt. Keep the existing
`test_disabled_region_markers_stripped_from_output` unchanged to lock in the default behavior.

**`tests/test_disabled_regions.py`** — add a full two-phase pipeline regression test inside (or alongside)
`TestPreprocessPromptLateDisabledRegions`. Build a prompt like:

```
%xprompts_enabled:false
Consider using more inclusive language for these new public @Input() fields.
The getters should be marked with the '@visibleForTemplate' annotation.
%xprompts_enabled:true
```

Call `preprocess_prompt_early(prompt).prompt`, then call `preprocess_prompt_late(..., file_ref_mode="validate")` on that
result. The call must NOT raise `SystemExit`, and the final output must not contain `%xprompts_enabled` (confirming the
late phase still strips markers at the end).

## Verification

1. `just install` in the current workspace.
2. `just check` — runs lint + mypy + tests. Confirm the two new tests pass and no existing tests regress.
3. Manual reasoning: for every other caller of `extract_prompt_directives` (`workflow_runner.py:174`,
   `run_agent_phases.py:86`, `_query.py:170`, `_prompt_bar.py:33`), the default parameter value is unchanged, so
   behavior is unchanged.

## Files touched

- `src/sase/xprompt/directives.py` — add `strip_disabled_markers` parameter, guard three strip calls.
- `src/sase/llm_provider/preprocessing.py` — pass `strip_disabled_markers=False` from `preprocess_prompt_early`.
- `tests/test_directives_extract.py` — add test for the new parameter value.
- `tests/test_disabled_regions.py` — add full-pipeline regression test.

## Out of scope

- Other callers of `extract_prompt_directives` keep default `strip_disabled_markers=True` behavior. Changing their
  behavior (e.g. showing markers in the `%edit` prompt bar pre-fill) is a separate UX question.
- No change to `make_mentor_changes.yml` — the template is already correctly wrapping output in markers; fixing the
  preprocessing pipeline is sufficient.
- No change to `_disabled_regions.py`. The marker regex and helpers are already correct and were fixed in earlier
  commits (`cef0d3df`, `7929921f`, `2edb4c87`) for orthogonal issues (whitespace, inline close).
