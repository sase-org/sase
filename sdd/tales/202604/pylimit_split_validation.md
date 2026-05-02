---
create_time: 2026-04-28 11:49:46
status: done
prompt: sdd/prompts/202604/pylimit_split_validation.md
---
# Plan: Fix pylimit_split Generated pysplit Validation

## Context

The `#sase/pylimit_split` workflow is a single hidden Python step that discovers over-limit Python files and launches
one wait-chained multi-prompt containing per-file `#sase/pysplit` agent prompts. `#sase/pysplit` has one required input,
`file_path`.

After adding per-file `%name:pysplit.<basename>` directives, the workflow now fails before executing:

```
Workflow 'sase/pylimit_split' validation failed:
  - Step 'launch_split_agents': #sase/pysplit missing required args: ['file_path']
```

## Diagnosis

The failure is from compile-time workflow validation, not from agent launch.

`validate_workflow()` scans all step content, including Python step source, for xprompt calls. The Python source
contains this f-string fragment:

```python
f"%name:{agent_name}\n#gh:sase #sase/pysplit:{path} %approve"
```

The validator's xprompt-call regex recognizes colon args such as `:src/foo.py`, backtick-delimited args such as
``:`src/foo.py` ``, command substitutions, and Jinja args. It does not treat Python f-string `{path}` as a colon arg. As
a result, it extracts the source text as a bare `#sase/pysplit` call with no positional args, then reports the required
`file_path` input as missing.

At runtime the f-string would have generated valid prompts, but static validation blocks the workflow first.

## Proposed Fix

Change the generated per-file prompt to backtick-delimit the file path argument:

```python
f"%name:{agent_name}\n#gh:sase #sase/pysplit:`{path}` %approve"
```

This fixes two things:

- Static validation sees the backtick-delimited colon argument in the Python source and counts `file_path` as provided.
- Runtime xprompt expansion already strips backticks from colon args, so launched split agents receive the original path
  value.

This is narrower and lower-risk than expanding validator support for arbitrary Python f-string expressions. The
validator should stay language-agnostic; the workflow can emit syntax it already understands.

## Tests

Add focused regression coverage in `tests/test_xprompt_pylimit_split.py`:

- Assert the bundled `pylimit_split.yml` passes `validate_workflow()`.
- Update prompt-shape assertions to expect backtick-delimited `#sase/pysplit` file path args.
- Add a check that generated agent names remain present in each segment, including the collision suffix behavior already
  introduced.

Run:

```bash
just install
pytest tests/test_xprompt_pylimit_split.py tests/test_workflow_validator_xprompt_calls.py tests/test_multi_prompt.py
just check
```

## Implementation Notes

Keep the change scoped to the bundled workflow and its tests. Do not change global xprompt parsing unless tests reveal
the backtick approach is not accepted by the runtime processor.
