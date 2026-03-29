---
create_time: 2026-03-29 18:12:36
status: done
---
# Plan: Fix #pr report-step false failure when optional meta fields are absent

## Problem Summary

Agents that run with embedded `#pr` can fail at post-step `report` even after a PR is created successfully. The failure surfaced as:

- `WorkflowExecutionError: Bash step 'report' failed: meta_pr_header=...`

Current `src/sase/xprompts/pr.yml` emits metadata in bash with trailing conditional commands:

- `[ -n "$result" ] && echo "meta_pr_url=$result"`
- `[ -n "$changespec_name" ] && echo "meta_changespec=$changespec_name"`

When the final condition is false, bash returns status `1` for the script, causing the workflow step to fail despite valid earlier output.

## Goals

1. Ensure `#pr` report step succeeds when optional fields are missing.
2. Preserve all existing metadata emission behavior (`meta_pr_header`, `meta_pr_url`, `meta_changespec`).
3. Add regression coverage proving optional missing fields do not fail the report logic.

## Implementation Strategy

1. Update `src/sase/xprompts/pr.yml` report bash step so optional output checks never determine the script's final failing exit code.
2. Prefer explicit `if` blocks for optional emissions rather than `&&` chaining on the final command.
3. Add a focused test module that mirrors the report-step shell behavior with representative `commit_result.json` payloads:
   - with full fields
   - without `changespec_name`
   - without `result`
   - without `message`
4. Assert the step-equivalent command exits `0` and emits only present `meta_*` keys.

## Validation

1. Run targeted tests for the new regression test file.
2. Run `just check` for full repo validation (required after source edits).

## Risks and Mitigations

- Risk: Changing shell script semantics could suppress required failure cases.
- Mitigation: Keep early guard (`[ -f "$RESULT_FILE" ] || exit 0`) and preserve existing parsing logic while only changing optional emission control flow.
