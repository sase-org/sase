---
create_time: 2026-05-08 16:02:40
status: done
prompt: sdd/prompts/202605/artifact_modal_open_all.md
---
# Plan: Add Artifact Modal Open-All Key

## Goal

Add an `A` key binding inside the agent artifact selection modal that opens every listed artifact in the same path that
is currently used when a user marks all artifacts with `m` and presses `enter`.

This is distinct from the existing app-level `A` binding, which opens the artifact picker from the agents tab. The new
behavior is scoped to the artifact picker after it is already open.

## Current Behavior

- `src/sase/ace/tui/actions/agents/_panels.py` implements `action_open_agent_artifacts()`.
  - It lists artifacts for the selected agent.
  - It pushes `AgentArtifactSelectionModal`.
  - The modal callback normalizes a single artifact or list of artifacts, then calls `_open_agent_artifacts()`.
  - `_open_agent_artifacts()` already supports one artifact or multiple artifacts, including tmux and same-pane viewers.
- `src/sase/ace/tui/modals/agent_artifacts_modal.py` implements the picker.
  - Selector keys open one artifact immediately.
  - `m` toggles marked rows.
  - `enter` opens the marked list when marks exist, otherwise the highlighted row.
  - The existing marked-list return path already preserves artifact list order.
- Existing tests cover single-key selection, marking, mark order, hints, and the agent action callback path for
  multi-artifact selections.

## Implementation Approach

1. Add a modal-local binding:
   - In `AgentArtifactSelectionModal.BINDINGS`, add `("A", "open_all", "Open All")`.
   - This should be modal-scoped and should not affect the app-level `A` binding.

2. Add an action method on `AgentArtifactSelectionModal`:
   - Implement `action_open_all(self) -> None`.
   - If there are artifacts, call `self.dismiss(list(self._artifacts))`.
   - Returning a list intentionally reuses the same callback branch as marked selection plus `enter`.
   - Do not depend on or mutate `_marked_indexes`; the action should behave as an immediate shortcut.

3. Update modal hint text:
   - Include `A: open all` in `_hint_text()`.
   - Keep the marked-count suffix behavior unchanged.

4. Add focused tests in `tests/ace/tui/modals/test_agent_artifacts_modal.py`:
   - Pressing `A` dismisses with all artifacts in original list order.
   - Pressing `A` works even when a subset is already marked, still returning all artifacts.
   - Optionally assert the hint includes `A: open all` and still appends `marked: N` after marking.

5. Consider existing callback tests sufficient for viewer behavior:
   - `tests/ace/tui/test_image_file_panels.py` already verifies that list selections route through
     `view_agent_artifacts()` and `view_agent_artifacts_in_tmux_pane()`.
   - Because the new modal action returns the same list shape as marked selection, no separate `_panels.py` behavior
     change should be needed.

## Verification

Run a targeted test set first:

```bash
just install
pytest tests/ace/tui/modals/test_agent_artifacts_modal.py tests/ace/tui/test_image_file_panels.py -q
```

Then, because this repo guidance requires it after source changes, run:

```bash
just check
```

## Risks and Edge Cases

- Textual uses `"A"` for the existing app-level capital-A binding, so using `"A"` in the modal binding is consistent
  with existing key naming.
- Lowercase artifact selector keys do not include uppercase `A`, and reserved lowercase navigation keys remain
  unchanged.
- The modal normally receives at least one artifact because the caller does not push it for an empty list. The action
  can still safely no-op or dismiss an empty list if an empty modal is ever constructed in a test or future path; the
  implementation should prefer the simple list-return behavior.
