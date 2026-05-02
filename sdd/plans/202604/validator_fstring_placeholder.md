---
create_time: 2026-04-28 12:03:27
status: done
prompt: sdd/prompts/202604/validator_fstring_placeholder.md
---

# Plan: Teach the workflow validator to recognize Python f-string `{path}` placeholders

## Context

Commit `83494e17` ("fix: validate pylimit split pysplit args") fixed a compile-time validation failure for the
`#sase/pylimit_split` workflow by editing `xprompts/pylimit_split.yml` to backtick-wrap the f-string path arg:

```python
# before
f"%name:{agent_name}\n#gh:sase #sase/pysplit:{path} %approve"
# after
f"%name:{agent_name}\n#gh:sase #sase/pysplit:`{path}` %approve"
```

That works at runtime — the xprompt processor already strips backticks from colon args — but it patches the symptom. The
root cause is in the validator: `_XPROMPT_PATTERN`'s colon-arg alternation in
`src/sase/xprompt/workflow_validator_extract.py:17-21` accepts `` `…` ``, `$(…)`, `{{…}}` (Jinja), and bare
alphanumeric/path characters, but **not** `{…}` (single-brace Python f-string placeholders).

Because `validate_workflow()` scans `step.python` source as a string, any future workflow whose Python step builds an
xprompt call with an f-string positional arg will trip the same validator and force its author to discover the same
backtick workaround.

## Goal

Make `#name:{var}` (single-brace placeholder) a recognized colon-arg form, semantically equivalent to the existing Jinja
`#name:{{ var }}` form. Then revert the YAML workaround so the workflow source reads naturally again.

## Approach

### 1. Extend the colon-arg regex

In `src/sase/xprompt/workflow_validator_extract.py`, add `\{[^}]*\}` to the colon-arg alternation, placed **after**
`\{\{[^}]*\}\}` so the double-brace Jinja form continues to match first:

```python
r":(`[^`]*`|\$\([^)]*\)|\{\{[^}]*\}\}|\{[^}]*\}|[a-zA-Z0-9_.~,/-]*[a-zA-Z0-9_~/-])"
```

Treat the matched `{…}` the same as `{{…}}`: as a runtime-resolved positional value that satisfies the slot. No change
needed to `validate_xprompt_call()` — once the colon arg is captured, it counts toward `positional_args` and the
required-arg check passes.

### 2. Revert the user-visible workaround

In `xprompts/pylimit_split.yml`, change:

```python
f"%name:{agent_name}\n#gh:sase #sase/pysplit:`{path}` %approve"
```

back to:

```python
f"%name:{agent_name}\n#gh:sase #sase/pysplit:{path} %approve"
```

### 3. Update / add tests

- `tests/test_xprompt_pylimit_split.py`:
  - Keep `test_workflow_passes_compile_time_validation` (still useful regression — verifies validator accepts the
    workflow as-is).
  - Update prompt-shape assertions back to the un-backticked form (`#sase/pysplit:src/foo.py`, etc.) in
    `test_step_two_files_launches_chained_multi_prompt`, `test_step_dedups_files_across_trees`,
    `test_step_names_same_stem_with_collision_suffix`.
- `tests/test_workflow_validator_xprompt_calls.py`:
  - Add a test that `extract_xprompt_calls("#foo:{path}")` returns one call with `positional_args == ["{path}"]`.
  - Add a test that ensures `{{ jinja }}` is still preferred over `{ x }` (the existing Jinja path keeps working).
  - Add a test using `validate_xprompt_call()` end-to-end: a Python step source string containing `f"#x:{path}"`
    validates as having the required positional input provided.

## Regression-risk audit

A grep across `xprompts/*.yml` for `#name:{…}` patterns turns up only the line being reverted. So the regex change has
no behavioral effect on any currently-bundled workflow other than fixing the case in question.

The broader risk surface is `prompt_part`, `bash`, and `agent` step content where `#name:{x}` could now be parsed as a
one-arg call instead of a bare call. In practice this is unlikely (literal `:{x}` after a hashtag is not a natural shape
in markdown or shell text), and it is symmetric with the existing handling of `{{ x }}`. The plan does not broaden this
surface beyond what is already accepted for Jinja.

## Out of scope

- Full Python AST inspection of `step.python` to extract xprompt calls precisely.
- Restricting the new alternation to Python-step contexts only — overkill given the audit result.
- Changes to runtime xprompt expansion (the backtick-stripping behavior) — unaffected.

## Verification

```bash
just install
pytest tests/test_xprompt_pylimit_split.py tests/test_workflow_validator_xprompt_calls.py tests/test_multi_prompt.py
just check
```
