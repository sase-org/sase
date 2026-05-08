---
create_time: 2026-05-08 15:54:01
status: done
prompt: sdd/prompts/202605/always_show_artifact_panel.md
---
# Always Show Agent Artifact Panel

## Context

Pressing `A` in the Agents tab currently lists artifacts for the selected agent, then opens a single available artifact
directly. This means a chat-only completed agent jumps straight to the chat transcript viewer instead of showing the
artifact selection panel. The existing `AgentArtifactSelectionModal` already handles a one-item artifact list, including
keyboard selection, `enter`, and cancel behavior, so this behavior is controlled by the action-level shortcut in
`src/sase/ace/tui/actions/agents/_panels.py`.

## Goals

- Always show the artifact selection panel whenever the selected agent has at least one artifact.
- Preserve current no-artifact warnings for running and completed agents.
- Preserve the viewer behavior after the user chooses an artifact: single selection opens one viewer, marked
  multi-select opens the sequence viewer, tmux routing remains unchanged, and focus returns to the agent list after the
  modal closes.
- Update tests and docs so the product contract is unambiguous.

## Non-Goals

- Do not change artifact discovery, ordering, synthesis, or explicit artifact storage.
- Do not change the external artifact viewer implementation or tmux-pane rendering.
- Do not redesign the modal UI beyond allowing it to appear for one artifact.

## Implementation Plan

1. Update `AgentPanelsMixin.action_open_agent_artifacts` to remove the `len(artifacts) == 1` direct-open branch. Once
   artifacts are non-empty, instantiate `AgentArtifactSelectionModal(artifacts)` for both one and many artifacts and use
   the existing callback to normalize and open the selection.

2. Keep `_open_agent_artifacts` unchanged. It is still the right lower-level helper because modal callbacks may select
   exactly one artifact or a marked list of multiple artifacts, and it already handles single vs sequence viewer
   routing.

3. Update action tests in `tests/ace/tui/test_image_file_panels.py`:
   - Replace expectations that `action_open_agent_artifacts()` immediately invokes the viewer for one artifact.
   - Assert the action pushes `AgentArtifactSelectionModal` for one artifact.
   - Invoke the modal callback with the single artifact to verify suspend/tmux/warning behavior still flows through the
     existing viewer helpers.
   - Keep no-artifact warning tests unchanged.

4. Update `tests/test_agent_artifact_e2e.py` to encode the new chat-only behavior: a chat-only agent should push the
   artifact modal instead of opening the chat transcript immediately, and selecting that artifact should still open the
   chat transcript.

5. Add or adjust modal tests only if a one-item panel gap appears during test updates. Current modal tests already cover
   one-artifact cancel behavior and general selection, so this may not require new modal-level coverage.

6. Update `docs/ace.md` Agent Artifacts text from “single opens directly; multiple open a picker” to the new invariant:
   pressing `A` opens the artifact panel when artifacts exist.

## Verification

- Run focused tests:
  - `pytest tests/ace/tui/test_image_file_panels.py -k "open_artifacts_action"`
  - `pytest tests/test_agent_artifact_e2e.py -k "agents_action"`
  - `pytest tests/ace/tui/modals/test_agent_artifacts_modal.py`
- Because this repo’s memory requires it after code changes, run `just install` if needed, then `just check` before
  final response.
