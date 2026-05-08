---
create_time: 2026-05-08 14:02:06
status: done
prompt: sdd/prompts/202605/artifact_marking_modal.md
---
# Plan: Artifact Modal Marking Flow Polish

## Goal

Refine the agent artifact selection modal so multi-artifact marking is faster and visually quieter:

- pressing `m` marks or unmarks the highlighted artifact, then advances the highlight to the next artifact;
- unmarked artifacts do not render an empty checkbox;
- marked artifacts continue to show a clear selected marker and the footer count continues to reflect the marked set.

## Current Behavior

The recent artifact-panel work added `AgentArtifactSelectionModal` in
`src/sase/ace/tui/modals/agent_artifacts_modal.py`. It supports marking artifacts with `m` and opening all marked
artifacts on `<enter>`, while preserving direct selector-key opening for single artifacts.

The modal currently renders `_artifact_option_text(..., marked=False)` with a dim `[ ]` prefix for every unmarked row.
That creates visual noise and makes unselected artifacts look like inactive controls. The same modal action toggles the
mark set and refreshes only the current option, but leaves `OptionList.highlighted` on the same row, so marking several
adjacent artifacts requires manual navigation between every mark.

## Implementation

1. Update the artifact row renderer in `src/sase/ace/tui/modals/agent_artifacts_modal.py`:
   - keep rendering a visible selected marker for marked artifacts;
   - remove the empty checkbox marker for unmarked artifacts;
   - preserve row alignment by using equivalent blank spacing only if needed, so labels and paths remain stable.

2. Update `AgentArtifactSelectionModal.action_toggle_mark()`:
   - toggle the current row in `_marked_indexes`;
   - refresh the row that changed;
   - move the highlighted index to the next artifact after marking/unmarking;
   - wrap from the final artifact back to the first artifact;
   - keep the existing guard behavior for empty/invalid highlights.

3. Keep modal dismissal semantics unchanged:
   - `<enter>` returns marked artifacts in list order when any marks exist;
   - `<enter>` returns the highlighted artifact when there are no marks;
   - selector keys still directly open a single artifact.

## Tests

Update `tests/ace/tui/modals/test_agent_artifacts_modal.py` to cover:

- unmarked option text does not contain an empty `[ ]` checkbox;
- marked option text still contains the selected marker;
- pressing `m` advances the highlighted artifact to the next row;
- pressing `m` on the final row wraps highlight to the first row;
- existing list-order return behavior still passes, adjusted where necessary because `m` now advances automatically.

## Verification

Run the focused modal tests first:

```bash
pytest tests/ace/tui/modals/test_agent_artifacts_modal.py
```

Because this repo requires full validation after code changes, run:

```bash
just install
just check
```
