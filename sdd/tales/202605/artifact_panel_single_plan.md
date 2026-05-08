---
create_time: 2026-05-08 17:17:34
status: done
prompt: sdd/prompts/202605/artifact_panel_single_plan.md
---
# Plan: Single Canonical Plan Artifact in Agent Artifact Panel

## Problem

The agent artifact picker can show multiple entries for the same logical plan:

- the archived plan path under `~/.sase/plans/...`
- the committed or workspace SDD plan path under `sdd/...`

The prompt-panel ARTIFACTS header already behaves closer to the desired UX by choosing a single plan path and rendering
workspace paths relative to the agent workspace. The modal is fed by `list_agent_artifacts()`, whose current core
artifact synthesis keeps multiple distinct plan paths and then appends explicit artifacts. Path-only dedupe cannot catch
the archived-vs-SDD duplicate because the paths are intentionally different files.

Desired behavior:

- The artifact picker should never list more than one `plan` artifact for an agent.
- When a committed/workspace SDD plan is the canonical plan, the picker should display it relative to the agent
  workspace, for example `sdd/tales/202605/unread_plan_done_jump.md`.
- Chat, image, PDF, markdown, and other explicit artifacts should keep existing ordering and behavior.

## Implementation Approach

1. Move the “choose the plan path” policy into the core artifact list path used by the modal.
   - Prefer `sdd_plan_path` when metadata says `plan_committed=True`.
   - Prefer the archived plan when `plan_committed=False`.
   - For historical records without `plan_committed`, preserve the existing prompt-panel compatibility rule: prefer the
     archived plan unless the SDD path is the only path, the same resolved path, or the archived path is missing and the
     SDD path exists.

2. Deduplicate explicit plan artifacts against the canonical default plan.
   - Treat `kind == "plan"` explicit rows as alternate representations of the same logical plan candidate.
   - Keep only one plan artifact in the final `list_agent_artifacts()` result.
   - Prefer the canonical metadata-derived plan when available, because it carries `workspace_dir` from `done.json` and
     lets the picker render relative paths.
   - If no metadata plan exists, keep one explicit plan artifact rather than dropping the plan entirely.

3. Keep display formatting in the TUI modal, but ensure it has the data it needs.
   - The modal already renders paths relative to `artifact.workspace_dir`.
   - The canonical default artifact should retain `workspace_dir`; tests will cover that the selected plan is displayed
     as `sdd/tales/...` when the plan lives under the workspace.

4. Add focused regression coverage.
   - Core facade tests for `plan_committed=True` producing one SDD plan, not archived plus SDD.
   - Core facade tests for an explicit plan duplicate not adding a second plan row.
   - Modal formatting test for workspace-relative display of the canonical plan.
   - Update any existing expectations that intentionally asserted multiple default plan artifacts.

5. Verify with focused tests first, then run the repo check command after code changes.
   - Focused: artifact facade and artifact modal/panel tests.
   - Final: `just check`, after `just install` if the workspace environment requires it.
