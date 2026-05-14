---
create_time: 2026-05-14 12:23:06
status: done
prompt: sdd/prompts/202605/agent_artifact_diff_fix.md
---
# Plan: Fix missing agent diff and stale artifact picker entries

## Problem Summary

The `zf` agent in the `home` bare git project created `sdd/research/202605/pixel-10-xl-verizon-plan-research.md` and
committed it as `64d0450`, but the ACE UI did not show a file-panel diff and the `A` artifact keymap reported no
artifacts.

The observed run metadata shows two independent failure modes:

- `~/.sase/projects/home/artifacts/ace-run/20260514114953/diff.stdout` contains the new-file diff, but
  `commit_result.json` and `done.json` both have `diff_path: null`. The file panel for completed agents only trusts
  `agent.diff_path`, so it correctly has nothing to show.
- Direct artifact synthesis for that same artifacts directory returns the chat transcript and generated markdown PDF, so
  artifact discovery is not inherently broken. The likely UI failure is stale caching in
  `_list_selected_agent_artifacts()`: it caches by agent row identity only, so an early empty artifact result can
  survive after `done.json` and generated artifacts appear for the same row.

## Root Cause

For the diff issue, `capture_pre_commit_diff()` currently calls `provider.diff(cwd)`. For git providers, that is
tracked-file-only output. A brand-new markdown file is untracked until the commit dispatch stages it, so the pre-commit
diff capture returns no content and never writes `commit_diff.diff`. The later embedded git workflow step can still
write `diff.stdout`, but ACE does not use that as the completed-agent authoritative diff path.

For the artifact issue, the artifact picker maintains `_agent_artifact_page_cache` keyed only by the stable row
identity. That key does not change when the agent transitions from running to done, when `done.json` appears, when
`markdown_pdf_paths` is populated, or when a daemon detail page changes. A cached empty list can therefore mask newly
available artifacts.

## Implementation Plan

1. Update commit diff capture.
   - Change `capture_pre_commit_diff()` to prefer `provider.diff_with_untracked(cwd)` when the provider supports it.
   - Fall back to `provider.diff(cwd)` for providers that do not implement untracked-file diffing.
   - Keep the existing target-path behavior: `commit_diff.diff` inside `SASE_ARTIFACTS_DIR`, otherwise
     `~/.sase/diffs/<cl>-<timestamp>.diff`.

2. Add focused tests for new-file commit diffs.
   - Extend `tests/workflows/test_commit_workflow.py` with a regression test proving `capture_pre_commit_diff()` uses
     `diff_with_untracked()` and writes a diff for an untracked/new-file patch.
   - Keep existing fallback coverage for providers exposing only `diff()`.

3. Fix artifact picker cache invalidation.
   - Replace the row-identity-only cache key with a key that includes a cheap artifact-state signature, or avoid caching
     empty pages that are likely to become non-empty after completion.
   - The signature should include the row identity plus state that changes when artifacts become available, such as
     status, `diff_path`, `response_path`, `extra_files`, and artifact directory marker mtimes for `done.json`,
     `agent_meta.json`, `plan_path.json`, and `markdown_pdfs/index.json`.
   - Keep the behavior local to the artifact picker; do not change artifact synthesis semantics.

4. Add focused tests for artifact cache freshness.
   - Add a unit test around `AgentPanelArtifactMixin._list_selected_agent_artifacts()` that first returns an empty
     artifact list for a row, then changes the row/artifact state and verifies a second lookup refetches instead of
     returning the cached empty list.

5. Verify locally.
   - Run the focused tests first:
     `just test tests/workflows/test_commit_workflow.py tests/ace/tui/actions/test_agent_artifact_image_open.py tests/ace/tui/test_agents_data_provider.py`
   - Because this repo requires it after code edits, run `just install` if the workspace environment is stale, then
     `just check`.

## Notes

This plan keeps backend behavior in the right layer. The diff capture change is commit-workflow Python glue around
existing VCS provider APIs. The artifact cache change is presentation/UI freshness logic in the ACE TUI. I do not expect
Rust core changes to be necessary unless verification shows daemon artifact projection itself omits artifacts that the
direct source reader finds.
