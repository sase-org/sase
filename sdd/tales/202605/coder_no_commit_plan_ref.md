---
create_time: 2026-05-02 12:36:54
status: done
prompt: sdd/prompts/202605/coder_no_commit_plan_ref.md
---
# Fix coder plan references for no-commit approvals

## Problem

The plan approval flow supports an ephemeral approval mode: approve the plan and run the coder, but do not commit the
plan file (`commit_plan=False`, `run_coder=True`). This is the mode exposed by the chat plugin "Approve" button after
the recent "Quest" rename.

That path can launch a coder prompt that references the generated SDD plan copy under `sdd/tales/...` (or
`.sase/sdd/...`) even though the plan was intentionally not committed. When the coder prompt also includes a VCS
workflow prefix such as `#gh:sase`, that workflow's pre-steps run before late prompt preprocessing and file-reference
expansion. Those pre-steps stash uncommitted and untracked files, so the uncommitted SDD plan copy can disappear before
`@sdd/tales/...` is expanded. The coder then starts with a broken or missing plan handoff.

The durable artifact in this flow is already available: `sase plan` archives the submitted plan into `~/.sase/plans/...`
before writing `.sase_plan_pending`. The no-commit coder should use that archived plan path, not the uncommitted SDD
copy.

## Current Behavior

- `sase plan <file>` formats the local plan and archives it via `save_plan_to_sase()`.
- The marker stores `"plan_file"` as the archived plan path and `"original_file"` as the workspace-local
  `sase_plan_*.md`.
- `handle_plan_marker()` receives `PlanApprovalResult(commit_plan=False, run_coder=True)` for no-commit approvals.
- It still writes SDD prompt/plan files best-effort.
- `_build_saved_plan_ref()` prefers `sdd_plan_path` whenever it exists, regardless of whether the plan will be
  committed.
- The coder prompt is assembled inline in `run_agent_exec_plan.py`, although docs describe it as the `#coder` handoff
  shape.

## Desired Behavior

For normal approve-and-commit:

- Keep the existing behavior: write the SDD plan, commit it when configured, and hand the coder the repo-relative SDD
  path so the implementation commit can mark the plan done and include the right plan metadata.

For no-commit approve-and-run:

- Still allow SDD files to be written as local user-visible artifacts.
- Do not rely on the uncommitted SDD file for the coder handoff.
- Set the coder plan reference to the archived `PlanApprovalResult.plan_file` / marker `"plan_file"` path.
- Keep `SASE_PLAN` behavior conservative: only point it at the SDD path when the plan is being committed; otherwise use
  the archived plan path so the commit workflow will not stage a plan file for version-controlled SDD projects.

## Implementation Plan

### 1. Pin the regression with a focused unit test

Update `tests/test_axe_run_agent_exec_plan_followups.py`.

Add a test for `commit_plan=False`, `run_coder=True`, VCS-prefixed coder launch:

- Arrange an archived plan path, e.g. `tmp_path / "archive" / "scratch_plan.md"`.
- Arrange a separate uncommitted SDD plan path, e.g. `tmp_path / "sdd" / "tales" / "202605" / "scratch_plan.md"`.
- Mock `write_sdd_files()` to return that SDD plan path.
- Return `PlanApprovalResult(action="approve", plan_file=<archive>, commit_plan=False, run_coder=True)`.
- Assert `state.current_prompt` contains `@<archive>` and does not contain `@sdd/tales/...`.
- Assert `os.environ["SASE_PLAN"]` is the archived path, not the SDD path.

Keep the existing `test_coder_prompt_uses_saved_sdd_plan_ref` for the commit/default path so the behavior split is
explicit.

### 2. Make coder plan-reference selection commit-aware

Update `src/sase/axe/run_agent_exec_plan.py`.

Change the approve branch so plan references are selected with the approval mode in mind:

- If `plan_result.commit_plan` is true and an SDD plan path exists, keep using `_build_saved_plan_ref(...)`.
- If `plan_result.commit_plan` is false, use `plan_result.plan_file` as the coder plan reference.
- Preserve the existing version-controlled versus local-SDD behavior inside `_build_saved_plan_ref()` for committed
  plans.

This is deliberately local to the coder follow-up path. Epic and legend approvals always force committed SDD files
before launching their follow-up agents, so their existing plan-ref helpers should stay unchanged.

### 3. Make `SASE_PLAN` match the selected mode

In the same approve branch:

- For `commit_plan=True`, keep the current behavior of pointing `SASE_PLAN` at `sdd_plan_path` when it exists, otherwise
  falling back to the archived marker path.
- For `commit_plan=False`, set `SASE_PLAN` to `plan_result.plan_file` / marker `"plan_file"` rather than
  `sdd_plan_path`.

This avoids a later coder commit workflow accidentally treating the uncommitted SDD copy as a plan it should stage.

### 4. Optionally reduce drift with the builtin `#coder` xprompt

The immediate bug can be fixed without refactoring prompt assembly, because the failure is the selected `plan_file` ref,
not the wording. Still, the docs currently say the coder prompt is built from `#coder`, while the code assembles the
same body inline.

After the regression fix is in place, evaluate a small cleanup:

- Either update the docs to say the generated prompt uses the same body as `#coder`, or
- Use `#coder:<selected_plan_ref>` in the assembled prompt body while keeping `model_prefix`, `resume_prefix`,
  `vcs_prefix`, custom coder instructions, and embedded rollover refs exactly where they are today.

Prefer the docs-only adjustment unless tests show the xprompt refactor is straightforward. The no-commit bug should not
depend on a broader prompt refactor.

### 5. Verification

Run focused tests first:

```bash
just test -- tests/test_axe_run_agent_exec_plan_followups.py tests/test_plan_utils.py tests/test_plan_rejection_response.py
```

Then run the required repo check because this repo was modified:

```bash
just check
```

Before running tests, run `just install` if the workspace environment is stale, per repo memory.

## Risks

- Absolute archived plan paths in coder prompts are intentional here. `process_file_references()` allows non-home
  absolute paths and maps home paths through `.sase/home/`, so the archived plan should remain readable after VCS
  pre-steps.
- For version-controlled SDD projects, no-commit approvals will no longer let the coder implementation commit stage or
  mark the SDD plan file done automatically. That matches the semantics of no-commit approval.
- If a user expects the uncommitted SDD copy to be the canonical handoff even in no-commit mode, this changes that
  behavior. The archived plan is the safer canonical artifact because it is created before approval and survives
  workflow workspace preparation.
