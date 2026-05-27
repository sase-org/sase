---
create_time: 2026-05-27 10:25:54
status: done
prompt: sdd/prompts/202605/agent_metadata_title_case_labels.md
---
# Agent Metadata Title-Case Labels Plan

## Goal

Make the Agents tab metadata panel use `Deltas:` and `Artifacts:` instead of `DELTAS:` and `ARTIFACTS:`. This brings
those two optional path-list sections into the same label style as ordinary metadata fields such as `Workspace:`,
`Model:`, `Name:`, `Bead:`, `Activity:`, and `Timestamps:`.

## Scope

This is a TUI presentation-only change for the selected-agent prompt panel. It should not change:

- persisted ChangeSpec `DELTAS:` syntax;
- ChangeSpec parser/persistence behavior;
- ChangeSpec detail-panel `DELTAS:` rendering;
- agent diff parsing, artifact discovery, file-hint mapping, or path styling;
- memory-read or step-metadata section headings.

The relevant rendering path is:

- `src/sase/ace/tui/widgets/prompt_panel/_agent_deltas.py`
- `src/sase/ace/tui/widgets/prompt_panel/_agent_artifacts.py`
- shared helper `src/sase/ace/tui/widgets/deltas_builder.py`
- header assembly in `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`

## Current State

`append_agent_deltas_section()` delegates to `build_delta_entries_section()`, which hardcodes `DELTAS:`. That helper is
also used by `build_deltas_section()` for ChangeSpec detail rendering, so changing the helper's default label directly
would unintentionally rename ChangeSpec UI output.

`append_agent_artifacts_section()` appends `ARTIFACTS:\n` locally, so the artifact label can be changed in the
agent-artifacts helper without touching shared ChangeSpec code.

Focused tests currently assert uppercase labels in the agent metadata path:

- `tests/ace/tui/widgets/test_agent_display_metadata.py`
- `tests/ace/tui/widgets/test_agent_deltas.py`
- `tests/ace/tui/widgets/test_agent_display_header_only.py`

There are also many uppercase `DELTAS:` assertions for ChangeSpec behavior, docs, persistence, and status display. Those
should remain uppercase.

## Design

Add a narrow label override for the reusable delta-entry renderer:

- keep `build_delta_entries_section()` defaulting to `DELTAS:` so ChangeSpec rendering remains unchanged;
- add a keyword-only `header_label: str = "DELTAS:"` or equivalent parameter;
- have `build_deltas_section()` rely on the default;
- have `append_agent_deltas_section()` pass `header_label="Deltas:"`.

Change artifact rendering locally:

- update `append_agent_artifacts_section()` to append `Artifacts:\n`;
- keep the existing style, glyph, indentation, sorting/dedupe, missing-path suffix, and hint mapping unchanged.

Keep the section ordering unchanged:

1. ordinary agent fields;
2. `Deltas:` when the selected agent has visible diff entries;
3. `Artifacts:` when the selected agent has visible artifact entries;
4. divider + `MEMORY READS` when present;
5. divider + `STEP METADATA` when present;
6. final metadata/content divider.

## Tests

Update focused expectations for agent metadata labels only:

- completed agent with `diff_path` renders `Deltas:\n`;
- agent without deltas or cheap headers omit `Deltas:`;
- hint mode renders `Deltas:\n  ~ [1] ...` and preserves the hint mapping;
- artifact path-list tests assert `Artifacts:\n` and confirm the old count summary still does not appear;
- header-only display asserts the title-case `Deltas:` label.

Add at least one negative assertion where it is useful to guard against stale uppercase labels in the agent panel,
without broadly banning `DELTAS:` in unrelated ChangeSpec tests.

Leave `tests/ace/tui/test_deltas_builder.py` expectations as `DELTAS:` to prove the shared helper's default behavior and
ChangeSpec-facing output are unchanged.

## Verification

After implementation, run focused tests first:

```bash
.venv/bin/python -m pytest \
  tests/ace/tui/widgets/test_agent_deltas.py \
  tests/ace/tui/widgets/test_agent_display_metadata.py \
  tests/ace/tui/widgets/test_agent_display_header_only.py \
  tests/ace/tui/test_deltas_builder.py
```

Then run the repo-required checks after file changes:

```bash
just install
just check
```

If a visual snapshot fails, inspect the diff. A casing-only label change in the Agents metadata panel is expected; any
snapshot update should be limited to that confirmed visual change.

## Risk

The main risk is accidentally changing the ChangeSpec `DELTAS:` presentation or persisted format by editing the shared
delta builder too broadly. Keeping the default uppercase label and passing the title-case label only from the agent
prompt-panel helper contains that risk.

The artifact change is lower risk because its label is local to the agent artifact helper. Tests should still cover
ordering and hint mode so the label cleanup does not mask a regression in the path-list behavior.
