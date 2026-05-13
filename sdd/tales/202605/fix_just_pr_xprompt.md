---
create_time: 2026-05-13 17:00:35
status: done
prompt: sdd/prompts/202605/fix_just_pr_xprompt.md
---
# Plan: Embed `#pr` in `fix_just` Fixer Agent Prompts

## Goal

When the project-local `xprompts/fix_just.yml` workflow launches its `fix_linters` or `fix_tests` agent step, the
launched agent should carry the standard PR workflow context by embedding the bundled `#pr` xprompt in the agent prompt.
That should let the existing xprompt executor expand `#pr`, set `SASE_COMMIT_METHOD=create_pull_request`, set a stable
`SASE_PR_NAME`, append any VCS-specific PR instructions, and allow the commit stop hook to create the PR/ChangeSpec when
the agent completes.

## Current Behavior

`xprompts/fix_just.yml`:

- runs `just install`;
- checks `just fmt-check`, `just lint`, and `just test`;
- commits formatting fixes directly in the `fix_fmt` bash step;
- launches `fix_linters` and `fix_tests` as agent steps when their checks fail.

The two agent prompts currently only contain:

```text
#gh:sase Can you help me fix the `just lint` command?
#gh:sase Can you help me fix the `just test` command?
```

Because they do not embed `#pr(...)`, they do not set the PR commit workflow environment for the spawned agent.

The workflow executor already supports the needed mechanics for agent steps:

1. `_execute_prompt_step()` preprocesses the step prompt and expands embedded workflow references before invoking the
   agent.
2. `_expand_embedded_workflows_in_prompt()` expands inline workflow refs such as `#pr(name)`, injects their
   `environment` values into `os.environ`, and appends `append_to_pr` tagged content when appropriate.
3. `invoke_agent(..., skip_preprocessing=True)` receives the already-expanded prompt, so this should be handled in the
   workflow prompt, not inside the runtime provider.

## Proposed Change

Update only the two agent steps in `xprompts/fix_just.yml`:

```yaml
- name: fix_linters
  if: "{{ decide_fixers.launch_linters }}"
  agent: |
    #gh:sase #pr(fix_just_linters) Can you help me fix the `just lint` command?

- name: fix_tests
  if: "{{ decide_fixers.launch_tests }}"
  agent: |
    #gh:sase #pr(fix_just_tests) Can you help me fix the `just test` command?
```

Use distinct deterministic names rather than deriving from timestamps or check output. These are long-lived automated
repair branches/ChangeSpecs, and the commit workflow can apply its existing suffix/prefix handling if a duplicate name
already exists.

Keep `fix_fmt` unchanged. It is a local deterministic formatting step that already commits/pushes directly and does not
launch an agent.

## Tests

Extend `tests/test_fix_just_workflow.py` with a focused regression test that executes the real workflow with mocked bash
steps and mocked `invoke_agent`.

Test shape:

- load the real `xprompts/fix_just.yml`;
- force `just lint` and `just test` to fail by passing step-output args, while skipping actual `just` commands as the
  existing test does;
- let the real prompt-step execution path run for `fix_linters` and `fix_tests`;
- patch `sase.llm_provider.invoke_agent` to capture each expanded prompt and return `AIMessage(content="ok")`;
- patch VCS/provider calls used by embedded `#pr` post-steps or make the fake response/worktree state no-op so the
  `check_changes` post-step does not require a real VCS operation;
- assert both captured prompts no longer contain raw `#pr(` but do include the `#pr` prompt-part instruction text from
  `src/sase/xprompts/pr.yml`;
- assert embedded workflow metadata includes `pr` for each launched step where practical;
- assert `SASE_COMMIT_METHOD`, `SASE_PR_NAME`, and `SASE_PR_STATUS` are populated for the active embedded PR workflow.

Also update the existing lightweight branch-selection assertion if needed so it still expects both agent steps when both
checks are forced to fail.

## Verification

Run focused tests first:

```bash
pytest tests/test_fix_just_workflow.py tests/test_xprompt_fix_just.py
```

Then follow repo instructions for changed files:

```bash
just install
just check
```

If the full check fails because of unrelated existing repository state, preserve the focused test results and capture
the failing command/output for follow-up rather than masking it with unrelated edits.

## Risks and Decisions

- `#gh:sase #pr(...)` is the same embedding pattern already used by the recent audit workflows, so it follows existing
  repo convention.
- The `#pr` environment variables are process-global during workflow execution. That is already how embedded workflow
  env injection works today; the test should clean up any touched env vars after running.
- Deterministic names can collide across repeated failing runs. The existing commit workflow already has PR-name
  suffixing/prefix behavior, so adding timestamp logic here would duplicate responsibility.
- This change intentionally does not alter xprompt expansion internals. The executor already has the required behavior,
  and changing it would expand the blast radius beyond the request.
