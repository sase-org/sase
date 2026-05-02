---
create_time: 2026-04-10 01:25:23
status: done
prompt: sdd/prompts/202604/commit_stop_hook_commit_message_scope.md
---

# Plan: Scope commit-stop-hook commit message guidance to the current commit only

## Objective

Update `sase_commit_stop_hook` so that when `SASE_COMMIT_METHOD` is anything other than `create_pull_request`, the hook
explicitly instructs agents (via `/sase_*_commit` skill guidance) to write a commit message that describes only the
changes being committed now, not the full PR.

## Context and Current Behavior

- The stop hook currently builds one generic instruction block in `_build_commit_instruction_message()` and appends
  PR-name constraints only for `create_pull_request` via `_build_name_instruction()`.
- The generic message says to commit using the resolved `/sase_*_commit` skill, but it does not constrain commit-message
  scope for non-PR methods.
- This allows agents to provide PR-wide summaries when the hook is asking for a regular commit/proposal message.

## Design Principles

1. Keep runtime parity: do not branch behavior by runtime capability; keep instruction quality uniform across
   Codex/Gemini/Claude.
2. Keep method semantics explicit:

- `create_pull_request`: no new “single-commit-only” constraint (PR text can be broader).
- non-PR methods (`create_commit`, `create_proposal`, and unknown/fallback methods): add explicit commit-message scope
  guidance.

3. Minimize surface area: change only instruction composition and tests; avoid touching unrelated hook flow (dedup, VCS
   detection, file listing, block emission).

## Proposed Implementation

1. Refine commit instruction builder

- Update `_build_commit_instruction_message(skill, commit_method)` to append method-sensitive message guidance.
- For non-`create_pull_request` methods, include clear language equivalent to:
  - Construct the message to describe only the changes in this commit.
  - Do not describe the full pull request or unrelated planned work.
- Preserve existing “Did you make these changes?” conditional and ignore-safe wording.

2. Preserve PR path behavior

- Keep `_build_name_instruction()` unchanged (still only applies to `create_pull_request`).
- Ensure PR method text does not include the new non-PR scope constraint.

3. Keep unknown method safe

- Treat any method that is not exactly `create_pull_request` as non-PR for scope guidance.
- Continue displaying the method token in the instruction text for observability.

## Test Plan

Extend `tests/test_commit_stop_hook.py` with focused unit tests on `_build_commit_instruction_message`:

1. Non-PR method includes scope restriction

- Input: `create_commit` (and/or `create_proposal`).
- Assert instruction includes “describe only this commit’s changes” style guidance.
- Assert instruction includes a prohibition on PR-wide messaging.

2. PR method excludes non-PR scope restriction

- Input: `create_pull_request`.
- Assert instruction omits the non-PR scope restriction text.

3. Unknown method defaults to non-PR restriction

- Input: unexpected method token.
- Assert scope restriction is present.

Keep existing `_emit_block` tests intact.

## Validation

1. Run workspace bootstrap/check commands as required for ephemeral clones:

- `just install`
- `just check`

2. If `just check` reports failures, iterate until green.

## Risks and Mitigations

- Risk: wording too weak and still interpreted as PR summary.
- Mitigation: use explicit prohibitive phrasing (“do not describe the entire PR”) plus positive requirement (“describe
  only the changes in this commit”).

- Risk: tests become brittle to exact sentence wording.
- Mitigation: assert on key phrases and semantic markers rather than full-string exact matches.

## Expected Outcome

When stop-hook commits are requested for non-PR commit methods, agents receive explicit guidance to produce commit
messages scoped to the actual commit contents only, reducing PR-wide commit-message misuse while preserving current
PR-name behavior for `create_pull_request`.
