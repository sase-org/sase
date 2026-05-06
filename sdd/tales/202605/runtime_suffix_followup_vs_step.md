---
create_time: 2026-05-06 10:05:01
status: done
prompt: sdd/prompts/202605/runtime_suffix_followup_vs_step.md
---
# Plan: Runtime Suffix Ownership For Follow-Up Workflows

## Context

Commit `1e2faf4e40d9` introduced `should_display_runtime_suffix()` to hide Agents-tab runtime suffixes for non-agent
workflow children. The predicate currently treats every row with `Agent.is_workflow_child` as a workflow step and then
allows only `step_type == "agent"`.

That is too coarse because `is_workflow_child` currently means either:

- a true workflow prompt-step marker, with `parent_workflow` and `parent_timestamp` populated; or
- a follow-up workflow/agent linked to a parent via `parent_timestamp` only, with no `parent_workflow`.

The `sase ace` snapshot exposes both cases:

- `1/1.legend sase (RUNNING) @aee.legend` is an appears-as-agent follow-up workflow linked to `@aee.plan` by
  `parent_timestamp`; it owns a live agent runtime and should show a ticking suffix.
- `1/1.plan main (DONE) @aee.plan` is the prompt-step marker inside the appears-as-agent parent workflow; its runtime
  duplicates the parent workflow's runtime and should not show a suffix.

The relevant persisted marker shape confirms this:

- `/home/bryan/.sase/projects/sase/artifacts/ace-run/20260506095615/agent_meta.json` gives `@aee.legend` a `role_suffix`
  and parent linkage, but the loaded row has `parent_workflow is None`, `appears_as_agent is True`, and no prompt-step
  `step_type`.
- `/home/bryan/.sase/projects/sase/artifacts/ace-run/20260506094840/prompt_step_main.json` loads as a true child step
  with `parent_workflow` set and `step_type == "agent"`.

## Design

1. Split runtime eligibility around runtime ownership instead of the broad `is_workflow_child` property.
   - Top-level rows and follow-up rows that are linked only by `parent_timestamp` should remain eligible, including
     appears-as-agent workflow follow-ups such as `@aee.legend`.
   - True workflow prompt-step rows should be evaluated separately. The stable marker for these rows is
     `parent_workflow is not None`, because loaders set it from the prompt-step marker's `workflow_name`.

2. Suppress duplicate prompt-step runtimes for appears-as-agent parents.
   - A prompt step with `step_type == "agent"` can be the internal `main` marker for an appears-as-agent workflow.
   - The visible parent/follow-up row owns the live runtime display, so the child marker should not render an additional
     suffix.
   - Implement this without disk reads in the runtime helper. Prefer deriving the needed fact from loaded `Agent`
     fields, and if necessary enrich the step agent during loading with an existing field already used by render/cache
     logic.

3. Keep non-agent workflow steps hidden.
   - True workflow prompt-step rows with `step_type` values like `bash`, `python`, `parallel`, or embedded pre-prompt
     setup steps should continue to return `(None, None)` from `compute_row_runtime()`.

4. Keep `runtime_suffix_ticks()` and `compute_row_runtime()` sharing the same eligibility helper.
   - A row with no visible runtime suffix should not participate in one-second patching.
   - A live follow-up workflow row such as `@aee.legend` should tick.

## Tests

Extend `tests/ace/tui/widgets/test_agent_list_runtime.py` with focused synthetic rows:

- A linked appears-as-agent follow-up workflow with only `parent_timestamp` set and `step_type is None` returns elapsed
  runtime and ticks while running.
- A true prompt-step `main` child under an appears-as-agent workflow does not render a suffix.
- Existing `bash` and `python` workflow child cases stay hidden.
- Existing ordinary top-level agent/workflow rows keep their suffix behavior.

If the implementation needs a loader-enriched flag or field on prompt-step agents, add a narrow loader test rather than
relying only on hand-built objects.

## Verification

Run the focused runtime widget tests first:

```bash
.venv/bin/python -m pytest tests/ace/tui/widgets/test_agent_list_runtime.py
```

Because this repo requires the full gate after changes, run:

```bash
just install
just check
```
