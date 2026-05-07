---
create_time: 2026-05-07 16:12:07
status: done
---
# Plan: Add `finally` To XPrompt Workflow Schema

## Problem

The xprompt workflow runtime supports top-level workflow steps with `finally: true`. The parser reads it into
`WorkflowStep.finally_`, the executor runs those steps after failures, validators enforce that finally steps come at the
end, and docs describe the field.

The YAML language server warning:

```text
finally: true
Property finally is not allowed.
```

is caused by `src/sase/xprompts/workflow.schema.json` having `additionalProperties: false` for step objects while
omitting the already-supported `finally` key.

## Scope

- Update the xprompt workflow JSON schema so top-level steps allow `finally` as a boolean.
- Keep `finally` disallowed for nested `parallel` substeps, matching runtime validation.
- Keep `finally` disallowed for `prompt_part` steps, matching runtime validation.
- Avoid touching `config/sase.schema.json`; it validates SASE config, not xprompt workflow YAML.

## Implementation

1. Add a top-level workflow step property:

   ```json
   "finally": {
     "type": "boolean",
     "description": "If true, this step runs even when a prior step has failed. Finally steps must appear at the end of the workflow.",
     "default": false
   }
   ```

2. Add `finally` to the existing `prompt_part` `not.anyOf` restrictions so the schema mirrors `parse_workflow_step()`
   rejecting `prompt_part` plus `finally: true`.

3. Do not add `finally` to nested `parallel.items.properties`, because nested steps reject `finally` at runtime and
   should continue to warn in editors.

4. Re-check nearby workflow step fields while editing. If the same schema block is missing adjacent currently-supported
   runtime fields that produce immediate LSP warnings in checked-in xprompts, include only narrowly-related schema fixes
   and keep runtime behavior unchanged.

## Verification

- Run a targeted JSON Schema validation that confirms `src/sase/xprompts/git.yml` is valid against
  `src/sase/xprompts/workflow.schema.json`; this specifically covers the checked-in `finally: true` and
  `artifact: stdout` usage.
- Run targeted tests for the existing finally parser/executor behavior:

  ```bash
  pytest tests/test_workflow_executor_finally.py
  ```

- Because this repo requires it after changes, run:

  ```bash
  just install
  just check
  ```
