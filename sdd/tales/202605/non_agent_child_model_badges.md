---
create_time: 2026-05-12 10:42:41
status: done
prompt: sdd/prompts/202605/non_agent_child_model_badges.md
---
# Plan: Hide Model Metadata And Provider Badges For Non-Agent Workflow Children

## Context

The Agents tab can render top-level agents/workflows and expanded workflow child entries. Some workflow children are
real LLM agent steps (`step_type == "agent"`), while others are local execution steps such as `bash`, `python`, or
`parallel`.

The current UI presentation uses the same `model` and `llm_provider` fields for every `Agent` row. Workflow step loaders
can populate those fields for non-agent child steps because the values are inherited from the surrounding workflow/run
metadata. That is useful as raw metadata, but it is misleading in the Agents tab: a selected bash child should not
display `Model: CLAUDE(opus)`, and its row should not get the Claude provider emoji.

The `Agent` model already exposes a useful semantic predicate:

- `Agent.is_agent_entry` is true for actual agent-process rows:
  - normal running agent rows,
  - workflow entries that appear as agents,
  - workflow child rows with `step_type == "agent"`.
- It is false for non-agent workflow child rows such as `bash`, `python`, and `parallel`.

This change should therefore be presentation-only in the Python TUI, not a loader/schema/backend change. We should
preserve stored `model` / `llm_provider` metadata in case other views or future tooling need it.

## Implementation Plan

1. Add a small presentation helper near the prompt-panel model rendering path, likely in
   `src/sase/ace/tui/widgets/prompt_panel/_helpers.py`.
   - The helper should answer whether the Agents-tab detail header should render the `Model:` field for a given `Agent`.
   - Intended rule: render the model unless the selected row is a workflow child that is not an agent entry.
   - In concrete terms, hide when `agent.is_workflow_child and not agent.is_agent_entry`.

2. Update the Agents-tab detail header rendering in `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`.
   - Replace the unconditional `append_model_field(header_text, agent.model, agent.llm_provider)` call with the
     helper-gated version.
   - This targets the `AGENT DETAILS` panel shown for selected child entries, including the snapshot's bash `diff` step.
   - Leave top-level workflow `WORKFLOW DETAILS` rendering alone unless tests reveal it is used for the same selected
     child case. The user request is specifically about non-agent child entries, not top-level workflow summaries.

3. Add a row-rendering helper or local predicate in `src/sase/ace/tui/widgets/_agent_list_render_agent.py`.
   - Keep provider emoji badges for top-level agent rows and workflow child rows with `step_type == "agent"`.
   - Suppress provider emoji badges for non-agent child rows, even when `agent.llm_provider` is populated.
   - This should change the example row from `1e/1 🐚 🎭 diff ...` to `1e/1 🐚 diff ...`.

4. Add focused regression tests.
   - Extend `tests/ace/tui/widgets/test_agent_display_metadata.py` or a nearby display-header test with:
     - non-agent workflow child with `step_type="bash"`, `model="opus"`, `llm_provider="claude"` does not include
       `Model:`.
     - agent workflow child with `step_type="agent"` still includes `Model:`.
     - ordinary top-level agent still includes `Model:`.
   - Update `tests/ace/tui/widgets/test_agent_display_list_rendering.py` provider badge tests:
     - change/replace the current workflow child provider emoji case so it explicitly covers an agent child.
     - add a bash child with provider metadata and assert the provider emoji is absent while the bash glyph remains.

5. Run targeted tests first.
   - `pytest tests/ace/tui/widgets/test_agent_display_metadata.py tests/ace/tui/widgets/test_agent_display_list_rendering.py`

6. Run repository verification after code changes.
   - Per repo memory, run `just install` before broader checks if the workspace may be stale.
   - Run `just check` before final response because this will modify repo files.

## Non-Goals

- Do not mutate loader behavior or persisted agent metadata.
- Do not remove model/provider data from real agent child rows.
- Do not change provider display in unrelated modals, notifications, logs, or top-level workflow summaries unless a
  failing test demonstrates those are part of the same Agents-tab selected-child path.
