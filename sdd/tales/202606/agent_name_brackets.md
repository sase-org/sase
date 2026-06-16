---
create_time: 2026-06-16 10:24:20
status: done
prompt: sdd/prompts/202606/agent_name_brackets.md
---
# Plan: Agent Name Brackets in ACE Agents Tab

## Context

The Agents tab currently shows persisted agent names in two presentation paths:

- The agent list row formatter appends an agent-name annotation as ` @<agent_name>` in gold (`#FFD700`).
- The agent metadata/header panel renders the first metadata row as `Name: @<agent_name>` in pink (`#FF87D7`).

This request is presentation-only. It should stay in the Python/Textual widget layer and should not touch core backend
agent identity, prompt parsing, project metadata, or file-reference behavior where `@` has separate meaning.

Relevant implementation areas:

- `src/sase/ace/tui/widgets/_agent_list_render_agent.py`
- `src/sase/ace/tui/widgets/_agent_list_styling.py`
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`

Relevant test areas:

- `tests/ace/tui/widgets/test_agent_list_runtime_rendering.py`
- `tests/ace/tui/widgets/test_agent_display_list_rendering.py`
- `tests/ace/tui/widgets/test_agent_display_name_model_metadata.py`
- `tests/ace/tui/widgets/test_agent_display_bead_metadata.py`
- Agents-tab PNG snapshots under `tests/ace/tui/visual/test_ace_png_snapshots_agents.py`

## Goals

1. In the agent list panel, replace the trailing ` @name` annotation with ` [name]`.
2. Keep the new list annotation the same gold/yellow used today for list agent names (`#FFD700`).
3. In the metadata panel's `Name:` field, remove the `@` prefix from named agents.
4. Style the named metadata value with the same gold/yellow used by the list annotation.
5. Preserve existing behavior for unassigned names, bead metadata derivation, tag labels, file-reference `@` syntax, and
   non-Agent-tab UI.

## Design

Introduce a small named style constant for the agent-name annotation color in the list styling module, for example
`_AGENT_NAME_ANNOTATION_STYLE = "#FFD700"`. Use that constant in both the list row formatter and the metadata header
builder. This keeps the color contract explicit without broadening the change into a theme refactor.

Update only the rendered strings:

- List rows: append ` [{agent.agent_name}]` instead of ` @{agent.agent_name}`.
- Metadata header: append `{agent.agent_name}\n` instead of `@{agent.agent_name}\n`.

Do not change `agent.agent_name`, identity keys, bead derivation, grouping, sorting, selection, cache keys, or any
prompt/file-completion `@` handling. The existing render cache key already includes `agent.agent_name`, and the format
change is code-version scoped, so no cache-key schema change is needed.

## Test Plan

Focused unit tests:

- Update list row formatter tests to assert ` [coder]` and reject ` @coder`.
- Update bead/list rendering tests to expect `◆ [sase-x.3]`, `◆ [sase-x.land]`, and related row strings.
- Update metadata name/model tests to expect `Name: reviewer` and assert the `reviewer` span uses `#FFD700`.
- Update bead metadata tests to expect `Name: sase-x.3`, `Name: reviewer`, etc., while keeping `Bead:` lines unchanged.

Visual tests:

- Run the relevant Agents-tab visual tests and inspect/update intentional PNG snapshot diffs if needed:
  - `agents_list_120x40`
  - `agents_selected_row_120x40`
  - `agents_metadata_zoom_modal_120x40`
  - any other Agents-tab snapshots touched by the shared fixture rows

Repo verification:

- Run `just install` before repo checks if this workspace has not already been refreshed.
- Run targeted pytest for the updated widget tests.
- Run `just test-visual` or the focused Agents-tab visual subset, updating committed PNG goldens only for intentional
  text/color diffs.
- Run `just check` before finishing, as required by the repo instructions after file changes.

## Risks and Mitigations

- Snapshot churn: The visible text width changes from ` @name` to ` [name]`, which adds one cell. Some row alignment or
  wrapping can shift in narrow views. Use the existing PNG snapshot suite to catch unintended layout changes.
- Over-broad `@` removal: Other `@` uses are meaningful, especially prompt file references and project/modal labels.
  Limit code changes to the two agent-name presentation sites.
- Color drift: Use a shared style constant rather than duplicating `#FFD700` again in the metadata renderer.
