---
create_time: 2026-05-21 15:05:50
status: done
prompt: sdd/prompts/202605/fix_just_test_deflake.md
---
# Plan: De-flake `fix_just` Test Failures Before Launching Agents

## Goal

Update the project-local `#sase/fix_just` xprompt workflow so a failed `just test` check is confirmed with one immediate
second run before the workflow launches the `fix_tests` repair agent.

The intended behavior is:

- if the first `just test` passes, behave exactly as today;
- if the first `just test` fails but the second run passes, treat the test check as green and do not launch an agent;
- if both runs fail, keep launching the existing `fix_tests` agent with the existing `#gh:sase #pr(fix_just_tests)`
  prompt.

## Current Shape

The workflow is in `xprompts/fix_just.yml`.

It currently runs:

1. `_just_install`: `just install`
2. `_just_fmt_check`: captures `just fmt-check` success as `success=true/false`
3. `_just_lint`: captures `just lint` success as `success=true/false`
4. `_just_test`: captures `just test` success as `success=true/false`
5. `decide_fixers`: reads the three typed booleans and emits `launch_*` booleans
6. fixer steps, including `fix_tests` when `decide_fixers.launch_tests` is true

The bash output parser collects `key=value` lines from stdout and ignores incidental output, and the `success: bool`
output declaration coerces `true/false` strings to Python booleans. That means the retry can stay inside the workflow
YAML without changing global workflow execution.

## Proposed Change

Change only the `_just_test` bash step in `xprompts/fix_just.yml`.

Recommended structure:

```bash
if just test; then
  echo "success=true"
elif just test; then
  echo "success=true"
else
  echo "success=false"
fi
```

This keeps the workflow executor step successful even when the test command fails, preserving the existing pattern where
the step records a boolean outcome rather than aborting the whole workflow. The only behavioral change is that
`success=false` now means "failed twice" instead of "failed once."

Optionally, add an extra parsed output such as `reran=true/false` or `first_success=true/false` if the TUI should expose
whether a deflake run happened. I would avoid this unless there is a concrete UI/reporting need, because the current
workflow only needs the `success` boolean and extra fields would expand the test surface for little product value.

## Tests

Add focused coverage in `tests/test_fix_just_workflow.py`, because that file already loads and executes the real
project-local workflow.

Test cases should avoid running the real full test suite. Use a fake `_execute_bash_step` or a patched subprocess path
to inspect and simulate the `_just_test` script behavior.

Recommended focused tests:

1. Structural test for the real workflow:
   - load `xprompts/fix_just.yml`;
   - find `_just_test`;
   - assert its bash body contains two `just test` invocations;
   - assert it still declares `output: { success: bool }`.

2. Workflow decision test for de-flaked test failures:
   - execute the real workflow with step-output args where `_just_fmt_check.success=True`, `_just_lint.success=True`,
     and `_just_test.success=True`;
   - assert `decide_fixers.launch_tests` is false and `fix_tests` is not launched.

3. Existing confirmed-failure behavior:
   - keep or extend the existing branch-selection test that passes `_just_test.success=False`;
   - assert `fix_tests` is still launched when the final `_just_test.success` value is false.

If the bash body itself is tested by execution rather than structure, run it under a temporary shell with a fake `just`
script on `PATH` that returns failure then success. That gives stronger assurance but is slightly more plumbing.

## Verification

After implementation:

1. Run targeted tests first:

```bash
pytest tests/test_fix_just_workflow.py tests/test_xprompt_fix_just.py
```

2. Because this repo's instructions require workspace refresh before checks after file changes, run:

```bash
just install
just check
```

If `just check` fails from an unrelated flake, rerun the failing command once before finalizing, and report both the
first and second result clearly.

## Risk

The main cost is runtime: a real failing `just test` now costs two full test runs before an agent starts. That is
intentional for this workflow because false-positive repair agents are more expensive than one confirmation run.

The blast radius should stay small if the change is kept in `xprompts/fix_just.yml`. There is no need to change the
workflow executor, workflow schema, Justfile, or global test runner.
