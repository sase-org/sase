---
create_time: 2026-05-05 11:53:11
status: done
prompt: sdd/prompts/202605/fix_inherited_vcs_tag_workflow_tests.md
---
# Fix Inherited VCS Tag Workflow Test Failures

## Goal

Diagnose and fix the GitHub Actions failures in `tests/test_workflow_executor.py::TestShouldHitl` around inherited VCS
workflow tags.

## Current Findings

The failing cases all exercise workflow prompt steps with `WorkflowExecutor(..., inherited_vcs_tag="#gh:sase ")`.

There are two independent symptoms:

1. The two prompt assertions expect a trailing newline after late prompt preprocessing. That newline is produced when
   `prettier` is installed, but `format_with_prettier()` explicitly returns the original text unchanged when `prettier`
   is missing or fails. GitHub Actions is therefore seeing `"#gh:sase Fix it"` while environments with prettier see
   `"#gh:sase Fix it\n"`.

2. The `%w` preservation case builds the prompt as `"%w #gh:sase Follow up\n---\n#gh:sase Second"` before early
   preprocessing. `preprocess_prompt_early()` then calls `extract_prompt_directives()`, which treats bare `%w` as a bare
   `%wait` directive and resolves it by consulting the most recently named agent. In CI there is no previous named
   agent, so directive extraction raises: `Bare '%wait' directive found but no previously named agent exists`.

## Root Cause

The inherited VCS tag behavior itself is mostly correct: untagged segments are prefixed and explicitly tagged segments
are preserved. The failures come from the workflow executor tests assuming incidental preprocessing behavior:

- Prompt text passed to `invoke_agent(skip_preprocessing=True)` is not guaranteed to have a trailing newline because
  late preprocessing depends on optional external `prettier`.
- A workflow unit test that only wants to verify inherited tag placement uses bare `%w`, but bare `%w` has real global
  stateful semantics during directive extraction.

## Implementation Plan

1. Make the inherited VCS tag workflow tests deterministic.
   - Stop asserting prettier-dependent trailing newlines for the prompt passed to the mocked provider.
   - Keep asserting the pre-embedded-workflow expansion input exactly, because that is the behavior under test.

2. Keep the `%w` directive semantics explicit in the preservation test.
   - Patch `sase.agent.names.get_most_recent_agent_name` in that test so bare `%w` resolution is deterministic and does
     not depend on CI/user agent history.
   - Add or tighten an assertion on the captured directives so the test still verifies that `%w` was parsed as wait
     metadata while the prompt body keeps the inherited VCS tag.

3. Run focused verification:
   - Install/update workspace dependencies with `just install` if needed.
   - Run the three failing tests directly.
   - Run adjacent parsing tests for `inherit_vcs_workflow_tag`.

4. Run repository verification required by memory after file changes:
   - Run `just check`.

## Risk

This should be a test-only fix unless inspection after implementation reveals the production code is relying on
optional-prettier newlines. The production behavior should not change just to satisfy a unit test expectation.
