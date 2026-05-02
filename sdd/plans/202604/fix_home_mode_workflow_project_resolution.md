---
create_time: 2026-04-08 21:07:18
status: done
prompt: sdd/prompts/202604/fix_home_mode_workflow_project_resolution.md
---

# Fix home-mode workflow resolution for namespaced workflows

## Goal

Ensure prompts like `#gh:sase #sase/pylimit_split %approve` execute the actual `sase/pylimit_split` workflow (and
therefore only spawn split agents when file paths are produced), instead of falling back to a plain LLM prompt.

## Diagnosis Summary

- The failing run (`home` artifacts at `20260408192154`) shows the raw prompt `#gh:sase #sase/pylimit_split` was sent
  directly to the model.
- No workflow state/step artifacts for `sase/pylimit_split` were created in that run, confirming the workflow never
  executed.
- In `run_execution_loop`, we always call `execute_workflow(..., project=ctx.project_name)`.
- In home mode, `ctx.project_name` is `"home"`, so anonymous-workflow flattening searches prompt/workflow catalogs under
  `project='home'`.
- Under `project='home'`, `sase/pylimit_split` is not discoverable, so flattening fails and the anonymous single-step
  agent (`main`) runs instead.

## Implementation Plan

1. Add explicit project-selection logic for workflow execution in `run_agent_exec.py`.

- Introduce a small helper that determines the project passed to `execute_workflow`.
- Behavior:
  - Non-home mode: keep existing behavior (`ctx.project_name`).
  - Home mode: pass `None` (let loader auto-detect from current workspace/cwd) instead of forcing `"home"`.

2. Wire the helper into `run_execution_loop`.

- Replace direct `project=ctx.project_name` with the helper result.
- Keep all other execution-loop semantics unchanged.

3. Add focused unit tests for the helper behavior.

- Verify non-home mode returns `ctx.project_name`.
- Verify home mode returns `None`.

4. Add a behavioral regression test around `run_execution_loop` argument passing.

- Patch `execute_workflow` and `_finalize_loop` to isolate the loop and capture invocation args.
- Assert home mode calls `execute_workflow` with `project=None`.
- Assert non-home mode still passes the concrete project.

5. Validate.

- Run targeted tests for the new/updated test module(s).
- Run full repo checks with `just check` per repo instructions.

## Risk/Tradeoff Notes

- This preserves current behavior for non-home runs.
- In home mode, project resolution now follows loader auto-detection, which is a more accurate default than hard-coding
  `home` for workflow discovery.
