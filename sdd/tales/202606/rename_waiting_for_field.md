---
create_time: 2026-06-29 08:43:37
status: done
prompt: sdd/prompts/202606/rename_waiting_for_field.md
---
# Rename Agents Metadata Wait Label

## Context

The Agents tab metadata header currently renders waited-agent metadata with the label `Waiting for:`. The requested UI
copy change is to shorten that metadata field label to `Wait`.

The relevant rendering path is presentation-only Python/TUI code in the prompt panel header builder. The wait data model
and wait behavior should stay unchanged: dependency names, status badges, duration waits, absolute-time waits, and
countdown text all keep their current formatting after the label.

## Implementation Plan

1. Update the Agents metadata header label in `src/sase/ace/tui/widgets/prompt_panel/_agent_display_header.py` from
   `Waiting for: ` to `Wait: `.

2. Update exact-string unit tests for waited-agent metadata in
   `tests/ace/tui/widgets/test_agent_display_waiting_warning.py` so they locate and assert the new `Wait: ...` line
   while preserving every existing dependency badge, unknown-agent badge, duration, and until-countdown expectation.

3. Update the aware wait-until header assertion in `tests/ace/tui/widgets/test_agent_display_list_rendering.py` from the
   old label to the new `Wait: until ...` label.

4. Update the Agents zoom visual test assertion in `tests/ace/tui/visual/test_ace_png_snapshots_agents_zoom.py` so it
   checks for the new label text. If the PNG golden changes only because of the shorter label, refresh the affected
   `agents_waiting_unknown_zoom_modal_120x40` golden with the normal visual snapshot update flow.

5. Search the codebase for remaining `Waiting for:` references after the edit. Keep unrelated phrases such as "Waiting
   for agent response..." untouched.

## Verification

Run the focused tests first:

```bash
just install
uv run pytest tests/ace/tui/widgets/test_agent_display_waiting_warning.py \
  tests/ace/tui/widgets/test_agent_display_list_rendering.py \
  tests/ace/tui/visual/test_ace_png_snapshots_agents_zoom.py
```

If product files change, finish with the repository-required check:

```bash
just check
```

For an intentional visual-only golden update, inspect the generated actual and diff artifacts before accepting the new
PNG snapshot.

## Risks

The main risk is missing a snapshot or exact assertion that encodes the previous label. A post-change exact search for
`Waiting for:` and a focused visual test run should catch this. The shorter label should reduce, not increase, layout
pressure in the metadata panel.
