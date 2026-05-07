---
create_time: 2026-05-07 19:40:29
status: done
prompt: sdd/prompts/202605/agent_metadata_deltas.md
---
# Plan: Agent Metadata DELTAS Field

## Goal

Add a `DELTAS` field to the agent metadata panel that looks and behaves like the existing ChangeSpec `DELTAS` display,
but is scoped to the selected agent's own file changes only. The `v` keymap must expose selectable hints for these file
paths.

## Current Shape

- ChangeSpec DELTAS rendering already lives in `src/sase/ace/tui/widgets/deltas_builder.py`.
- It accepts `DeltaEntry` / `DeltaLineStats` values, renders summary and expanded path rows, and already supports
  `v`-style file hints for visible entries.
- Agent metadata rendering lives in `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py` via
  `build_header_text()`.
- Agent `v` handling re-renders the prompt panel through `AgentHintsDisplayMixin.update_display_with_hints()`, which
  currently hints paths found by regex in header/prompt/chat text.
- Agent file changes are already surfaced through the file panel:
  - Completed agents prefer `agent.diff_path`, which is the saved diff for that agent.
  - Active agents use `diff_with_untracked()` for the selected agent workspace.

## Design

1. Reuse the existing `DeltaEntry` and `DeltaLineStats` model instead of adding a new model.
2. Add a small agent-specific DELTAS helper module near the prompt panel or agent widgets. Its job:
   - Read the agent's authoritative diff source:
     - `agent.diff_path` for completed agents when available.
     - live workspace diff for active agents, matching the file panel's behavior.
   - Parse unified diff text into per-file `DeltaEntry` rows.
   - Derive change type from diff metadata:
     - new file / `--- /dev/null` => `A`
     - deleted file / `+++ /dev/null` => `D`
     - otherwise => `M`
   - Derive semantic line stats the same way ChangeSpec DELTAS does:
     - raw added/deleted line counts exclude diff headers.
     - paired add/remove counts become `modified`.
     - unpaired counts become `added` / `removed`.
     - binary diffs become `binary` when detectable.
3. Keep scope strict:
   - Do not read `changespec.deltas`; those represent the whole CL.
   - Do not fall back from a completed agent without `diff_path` to a reused workspace or branch-level diff, because
     that could include unrelated changes.
   - If there is no authoritative agent diff, omit the field.
4. Render `DELTAS` inside `AGENT DETAILS`, after the timestamp metadata and before arbitrary `meta_*` fields. Use the
   existing DELTAS rendering style and fully expanded rows so each file shows its line stats immediately.
5. Make `v` work by extending the agent hint-rendering path to render the same DELTAS section with
   `show_file_hints=True`, using the resolved agent workspace directory for relative paths.
6. Preserve the cheap j/k header path:
   - `build_header_text(..., cheap=True)` should skip DELTAS because computing or reading diffs can touch disk/VCS.
   - The debounced full render will populate DELTAS shortly after selection settles.

## Test Plan

- Unit-test the unified diff parser:
  - added file with only added lines.
  - deleted file with only removed lines.
  - modified file with paired additions/removals producing `modified` counts.
  - mixed modifications producing added/modified/removed semantic stats.
  - rename or path metadata picks the displayed target path where appropriate.
  - binary diff produces a binary line stat when detectable.
- Agent header tests:
  - completed agent with `diff_path` renders `DELTAS:` and per-file stats.
  - completed agent without `diff_path` omits `DELTAS`.
  - cheap header omits `DELTAS`.
- Agent hint tests:
  - `update_display_with_hints()` inserts numbered hints into DELTAS rows.
  - hint mappings resolve relative DELTAS paths under `agent.workspace_dir` when present.
- Run focused tests first, then `just install` if needed and `just check` before finishing because this repo requires it
  after code changes.
