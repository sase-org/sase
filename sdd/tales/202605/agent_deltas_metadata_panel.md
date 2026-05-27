---
create_time: 2026-05-27 09:54:15
status: done
prompt: sdd/prompts/202605/agent_deltas_metadata_panel.md
---
# Agent Deltas Metadata Panel Plan

## Goal

Show a beautiful, low-noise `Deltas:` / `DELTAS:` field in the Agents tab metadata header for the currently selected
agent. The field should list the files that agent added, modified, or deleted, using the same compact glyph language as
the ChangeSpec `DELTAS` field.

## Design

- Treat this as presentation-layer behavior in the ACE TUI. The backend/core boundary stays untouched because the file
  list is only being rendered for the selected agent panel.
- Reuse the existing ChangeSpec delta vocabulary:
  - `DeltaEntry` and `DeltaLineStats` remain the shared data shape.
  - `+`, `~`, and `-` represent added, modified, and deleted files.
  - Existing DELTAS path styling, basename emphasis, and line-stat tokens should be reused so users do not have to learn
    a second visual language.
- Source the selected agent's own changes from the same authority as the file panel:
  - completed agents use `agent.diff_path` when present;
  - active agents use the live workspace diff path already exposed by `get_agent_diff()`;
  - completed agents without a saved diff omit the field rather than falling back to a possibly reused workspace.
- Keep j/k navigation fast:
  - cheap header rendering must not compute deltas or touch disk/VCS;
  - the debounced full detail refresh can parse and render deltas after selection settles.
- Place the field in `AGENT DETAILS` near the other metadata, after timestamps and before artifact/memory/step metadata.
  This keeps volatile agent output below stable identity/timing metadata and keeps file-oriented metadata grouped.
- Preserve file-hint mode:
  - when `v` re-renders the agent detail header with path hints, DELTAS rows should receive selectable hint numbers;
  - relative paths should resolve under the selected agent's workspace directory.

## Implementation Steps

1. Audit the existing agent-deltas helper path and confirm whether it already satisfies the requested behavior.
2. If gaps remain, implement them in the smallest layer:
   - diff parsing / `DeltaEntry` conversion in the agent prompt-panel helper;
   - rendering through `build_delta_entries_section()`;
   - metadata-header wiring through `DetailHeaderSummary` and `build_header_text()`.
3. Add or adjust focused tests for:
   - added, modified, deleted, renamed, mixed-stat, and binary diff parsing;
   - completed agents with and without `diff_path`;
   - cheap header omission;
   - `v` file hints on delta rows.
4. Add a lightweight visual/assertion check if the current snapshots do not exercise the rendered field.
5. Run focused tests first, then `just install` and `just check` before finishing if any code files change.

## Current Observation

Initial exploration found that this workspace already contains an implementation named
`feat: show agent deltas in metadata`, including `src/sase/ace/tui/widgets/prompt_panel/_agent_deltas.py` and focused
tests. I will treat the next step as an audit/polish pass rather than duplicating that implementation.
