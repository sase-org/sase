---
create_time: 2026-06-02 23:12:59
status: done
prompt: sdd/prompts/202606/workflow_variables.md
---
# Rename Step Metadata to Workflow Variables

## Context

The current ACE metadata panel has two adjacent concepts:

- Agent-published string variables from `sase var set`, currently rendered by `_append_output_variables_section()` as
  `OUTPUT VARIABLES`.
- XPrompt workflow step outputs whose keys start with `meta_*`, currently rendered as `STEP METADATA`.

The requested rename is for the second concept: workflow-produced output variables should be labeled
`WORKFLOW VARIABLES`. This better describes values produced by xprompt workflow execution and pairs naturally with agent
variables.

Current exact `STEP METADATA` render sites are:

- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`
- `src/sase/ace/tui/widgets/prompt_panel/_workflow_render.py`

Current exact test/doc references are:

- `tests/ace/tui/widgets/test_agent_display_step_metadata.py`
- `tests/ace/tui/widgets/test_agent_display_output_variables.py`
- `tests/ace/tui/widgets/test_agent_display_workflow_async.py`
- `tests/ace/tui/widgets/test_prompt_panel_header.py`
- `docs/ace.md`

Historic SDD prompt/tale files also mention `STEP METADATA`, but those are project-history artifacts and should not be
rewritten for this UI label rename.

## Plan

1. Add a small shared section-label constant near the prompt-panel rendering helpers, or otherwise make the rename in
   both live render paths without changing extraction behavior.
   - Keep `extract_meta_fields()` and the underlying `meta_*` data model unchanged.
   - Keep the same title-cased row labels, divider behavior, ordering, and conditional rendering.
   - Render `WORKFLOW VARIABLES` in both the selected-agent detail header and the workflow-detail view.

2. Update focused tests to assert the new label while preserving the behavior they already guard.
   - Presence/absence of the section when displayable `meta_*` fields do or do not exist.
   - Divider placement before the section.
   - Ordering relative to output/agent variables, artifacts, and memory reads.
   - Workflow-detail rendering from `workflow_state.json`.

3. Update user-facing documentation in `docs/ace.md`.
   - Replace the `STEP METADATA` bullet with `WORKFLOW VARIABLES`.
   - Describe these as xprompt workflow output variables from `meta_*` step outputs.
   - Clarify that routing keys such as `meta_project`, `meta_changespec`, and `meta_workspace` are still promoted into
     normal header fields.

4. Validate with the focused test subset first, then run the repo-required check.
   - Run the relevant prompt-panel tests after the rename.
   - Because implementation/docs files will change, run `just install` if needed and then `just check` before finishing.

## Non-Goals

- Do not rename the underlying `meta_*` keys or workflow state schema.
- Do not rewrite archived SDD research/tale/prompt files.
- Do not change persistence for `sase var set` variables.
