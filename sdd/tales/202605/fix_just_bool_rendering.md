---
create_time: 2026-05-12 17:44:39
status: done
prompt: sdd/prompts/202605/fix_just_bool_rendering.md
---
# Plan: Fix `fix_just` Python Boolean Rendering

## Problem

The `fix_just` xprompt workflow fails in its hidden `decide_fixers` Python step after the `just` check steps emit typed
boolean outputs. The bash outputs are parsed and coerced correctly into Python `bool` values, but the workflow embeds
them into Python source with bare Jinja interpolation:

```python
fmt_success = {{ _just_fmt_check.success }}
```

The workflow template renderer intentionally finalizes bare booleans as lowercase strings (`true`/`false`) so bash and
YAML-style contexts remain convenient. That makes the rendered Python invalid:

```python
fmt_success = true
```

The renderer already provides a Python-aware `tojson` filter that produces `True`, `False`, and `None`, and tests
already pin that contract. The bug is therefore in the workflow using the wrong interpolation form for Python code, not
in bash output parsing or type coercion.

## Scope

- Update `xprompts/fix_just.yml` so the `decide_fixers` Python step renders prior boolean outputs with `| tojson`.
- Add a focused regression test that loads the real `xprompts/fix_just.yml`, skips the expensive `just` steps by
  supplying typed step inputs, executes `decide_fixers`, and verifies:
  - the workflow does not raise `NameError`;
  - `decide_fixers` emits typed boolean outputs;
  - fixer branch conditions are computed correctly.
- Avoid changing global Jinja finalization behavior because that would risk bash/condition/rendering regressions.

## Verification

1. Run the new focused test.
2. Run nearby workflow executor/xprompt tests if the focused test exposes shared behavior.
3. Because this repo requires it after file changes, run `just install` if needed and then `just check` before
   finishing.

## Risk

The change should be low-risk because it only affects three Python assignments in a project-local workflow and uses an
existing renderer filter whose behavior is already covered. The main regression risk would be missing another Python
workflow that embeds bare booleans, so the test should exercise the real workflow rather than an isolated synthetic
copy.
