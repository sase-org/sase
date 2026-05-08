---
create_time: 2026-05-08 12:47:39
status: done
prompt: sdd/prompts/202605/agent_artifacts_metadata_field.md
---
# Plan: Fix Agents-Tab ARTIFACTS Metadata Field

## Goal

Correct the `ARTIFACTS` field in the `sase ace` Agents-tab metadata panel so it behaves like a path list, not a count
summary:

- render it below the agent `DELTAS` field;
- render entries in the same visual family as expanded `DELTAS` entries, but without per-file line-count tokens;
- include only proposed plan artifacts and artifacts explicitly linked with `sase artifact create`;
- make every displayed artifact path selectable through the existing `v` file-hint keymap.

## Current Behavior

Recent artifact-panel commits added `_agent_artifact_summary()` in
`src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`. It renders `ARTIFACTS: 2 (chat, image)` near the top of
the agent header, above fields like `Mode`, and it includes all artifacts returned by `list_agent_artifacts()`.

The agent `DELTAS` section is rendered later by `append_agent_deltas_section()` after `Timestamps`. Hint mode already
routes through the same header builder and passes a `HeaderHintState`, so paths appended there can participate in the
`v` keymap if they update `hint_state.hint_mappings`.

The artifact domain currently synthesizes default artifacts from `done.json`, `agent_meta.json`, and `plan_path.json`,
and explicit artifacts from the persistent `~/.sase/artifacts/index.jsonl` created by `sase artifact create`.

## Design

Replace the summary-only metadata field with an expanded path-list builder.

1. Add an agent-artifact metadata helper for the prompt panel.
   - It should resolve the selected agent's artifacts directory and collect candidate artifacts.
   - It should include explicit artifacts linked by `sase artifact create`.
   - It should include at most the proposed plan artifact for the agent.
   - It should exclude default chat, image, generated PDF, and unrelated default artifacts from this metadata field.

2. Choose the displayed plan path according to plan commit state.
   - Prefer the committed SDD plan path when metadata proves the plan was committed, and display it relative to the
     agent workspace when possible.
   - Otherwise display the archived `~/.sase/plans/...` plan path.
   - Record/propagate an explicit `plan_committed` metadata flag during plan handling so future agents do not need to
     guess from path shape.
   - Keep a conservative fallback for historical artifacts that predate `plan_committed`: use `sdd_plan_path` only when
     it is the only viable plan path or can be safely treated as committed; otherwise prefer the archived plan path.

3. Render `ARTIFACTS` immediately after `DELTAS`.
   - Remove the old `_agent_artifact_summary()` placement above `Mode`.
   - After `append_agent_deltas_section(...)`, append `ARTIFACTS:\n` when there are entries.
   - Use the same path styling approach as DELTAS: indented rows, styled directory/basename, stable sort/dedupe by
     resolved path.
   - Do not append line stats or any added/removed/modified count tokens.

4. Integrate with hint mode.
   - When `HeaderHintState` is present, assign a hint number to each visible artifact path.
   - Map the hint to the actual filesystem path, not merely the displayed relative or `~` path.
   - This lets the existing Agents-tab `v` flow view the file, open it in the editor, or copy the path without new
     keymap code.

5. Add focused tests.
   - Header rendering places `ARTIFACTS` after `DELTAS`.
   - The field lists paths, not counts/kind summaries.
   - Chat/image/default non-plan artifacts are excluded.
   - Explicit artifacts from the index are included.
   - Uncommitted proposed plans display as `~/.sase/plans/...`.
   - Committed proposed plans display as workspace-relative SDD paths and map to the absolute path in hint mode.
   - Cheap header rendering still does not touch artifact storage.

## Expected Files

- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`
- likely new helper near the prompt-panel renderer, e.g. `src/sase/ace/tui/widgets/prompt_panel/_agent_artifacts.py`
- `src/sase/axe/run_agent_exec_plan.py`
- `src/sase/axe/run_agent_helpers.py`
- tests under `tests/ace/tui/widgets/` and possibly `tests/test_axe_run_agent_exec_plan_followups.py`

## Verification

After code changes:

- run targeted tests for agent metadata artifacts and plan metadata propagation;
- run `just install` if needed, then `just check` before handing back, per repo instructions.
