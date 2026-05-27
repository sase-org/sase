---
create_time: 2026-05-27 10:11:45
status: done
prompt: sdd/prompts/202605/agent_row_file_change_pencil.md
---
# Agent Row File-Change Pencil Plan

## Goal

Add a small pencil marker to Agents-tab rows when the row is associated with an agent that produced file changes,
creations, or deletions. The marker should make changed agents easy to scan in the list while preserving the current
fast j/k navigation behavior.

## Relevant Context

- Agent rows are rendered by `src/sase/ace/tui/widgets/_agent_list_render_agent.py`.
- Full list rebuilds and single-row patches both flow through `format_agent_option()` / `cached_format_agent_option()`.
- Row rendering is cache-keyed in `src/sase/ace/tui/widgets/_agent_list_render_cache.py`; any newly visible row state
  must be part of `agent_render_key()`.
- The detail panel already has an accurate DELTAS path via `src/sase/ace/tui/widgets/prompt_panel/_agent_deltas.py`, but
  that path reads/parses diffs and can call live VCS helpers for running agents. It belongs in the debounced detail
  path, not the hot row-rendering path.
- Loaded agents already carry `agent.diff_path` when SASE has a saved diff artifact. That field is populated by done
  loaders, workflow loaders, workflow-step loaders, and snapshot mirrors; follow-up code diffs are propagated to the
  parent plan/workflow row in `_agent_status_overrides.py`.

## Design

- Treat the row pencil as a cheap presentation hint: render it when `agent.diff_path` is present.
- Do not call `get_agent_diff()`, parse unified diffs, stat files, or invoke VCS providers during row rendering.
- Running agents without a persisted `diff_path` will not get the pencil until an existing loader path associates them
  with a saved diff. This is deliberate: live worktree probing belongs in the detail/file panel, not every list row.
- Place the marker after the status/fold annotation and before bead / `@agent_name` annotations. This keeps row identity
  stable (`name (STATUS)` still reads normally) while grouping the pencil with other row metadata badges.
- Define the glyph and style with the other row constants in `_agent_list_styling.py`; use the requested pencil emoji.
- Include the rendered condition in the row render cache key so a later refresh that adds or removes `diff_path` cannot
  reuse a stale row.

## Implementation Steps

1. Add a row-level pencil constant/style near the existing badge constants in `_agent_list_styling.py`.
2. Add a tiny helper or inline condition in `_agent_list_render_agent.py` for the cheap signal
   (`bool(agent.diff_path)`).
3. Append the pencil marker in `format_agent_option()` after fold annotation handling and before bead / agent-name
   annotations.
4. Add the same cheap signal to `agent_render_key()` in `_agent_list_render_cache.py`.
5. Add focused tests:
   - a row with `diff_path` renders the pencil;
   - a row without `diff_path` omits it;
   - the marker placement does not collapse tag, fold, bead, or `@agent_name` annotations;
   - the render cache key changes when `diff_path` appears or disappears.
6. Run focused pytest for the row-rendering/cache tests, then `just install` and `just check` after source changes.

## Non-Goals

- Do not broaden the loader or Rust-core API for this UI-only badge.
- Do not parse diff contents for every row.
- Do not introduce a live-diff indicator for running agents in this pass.
- Do not update visual snapshots unless a focused test shows an existing snapshot intentionally covers this row shape.

## Acceptance Criteria

- Agents-tab rows with a saved diff artifact show a pencil marker.
- Rows without a saved diff artifact render exactly as before.
- j/k navigation and row patching remain on the existing cached rendering path.
- Focused tests and full repo validation pass after implementation.
