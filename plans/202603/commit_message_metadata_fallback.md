---
create_time: 2026-03-30 13:54:05
status: done
---

# Diagnose and Fix Missing Commit Message Metadata in Agents Panel

## Objective

Ensure the Agents metadata panel reliably shows `Commit Message` for agents that create commits, including
Mercurial-based environments (e.g. `sase-google`) where commits may be performed through the post-completion hook path
rather than embedded `#commit` post-steps.

## Problem Framing

Current metadata rendering depends on `meta_*` fields collected from `prompt_step_*.json` outputs. In stop-hook commit
flows, `sase commit` writes `commit_result.json` (with commit message/result metadata), but no `meta_commit_message` may
be emitted into prompt-step outputs. As a result, TUI metadata has no `Commit Message` field even though a commit
succeeded.

## Plan

1. Map the metadata pipeline end-to-end

- Confirm where `Commit Message` is rendered in the Agents panel.
- Confirm where loaders source `meta_*` fields for RUNNING/DONE and workflow agents.
- Confirm what fields exist in `commit_result.json` for successful commit/propose operations.

2. Introduce a metadata fallback from `commit_result.json`

- Add a focused helper in the artifact loader layer that reads `commit_result.json` and derives display metadata fields:
  - `meta_commit_message` from `message`.
  - `meta_new_commit` from `result` for commit/proposal methods.
  - `meta_changespec` from `changespec_name` when present.
- Keep behavior additive and non-destructive:
  - Never override existing `meta_*` keys already provided by prompt-step outputs.
  - Safely no-op on missing/malformed files.

3. Apply fallback consistently across loader entry points

- Ensure fallback metadata is applied for:
  - DONE/home agents loaded from artifact markers.
  - Workflow parent agents (`appears_as_agent` paths).
  - Workflow step agents where appropriate.
- Preserve existing precedence and dedup semantics.

4. Add regression tests

- Add/extend tests to cover the stop-hook scenario where:
  - `commit_result.json` exists with message/result.
  - `prompt_step_*.json` does not contain `meta_commit_message`.
  - Agent metadata includes synthesized commit fields, enabling `Commit Message` display.
- Add at least one precedence test proving explicit prompt-step `meta_commit_message` is not overwritten.

5. Validate and harden

- Run targeted tests for affected loader/rendering modules first.
- Run full repo checks as required (`just install` then `just check`).
- Summarize root cause, exact fix, and expected runtime parity impact (Git + Mercurial).

## Expected Outcome

Agents that commit via post-completion hook paths will show `Commit Message` in AGENT DETAILS without requiring embedded
`#commit` reporting steps. This restores consistent metadata behavior across runtimes and VCS providers.
