---
create_time: 2026-06-16 10:51:11
status: done
prompt: sdd/prompts/202606/agent_name_unbracket_list.md
---
# Plan: Remove Square Brackets Around Agent Names in the Agents List

## Context

The previous approved change replaced the Agents-tab list annotation from ` @name` to ` [name]` and separately changed
the metadata header from `Name: @name` to `Name: name` with the same gold color used by list annotations.

The new request is narrower: remove the square brackets that wrap persisted agent names in the agent list panel. The
metadata header already renders the bare name and should stay that way. Other square-bracket UI affordances, such as
hint keys, marked-row badges, debug type badges, status text, and log prefixes, are not part of this request.

Relevant implementation areas:

- `src/sase/ace/tui/widgets/_agent_list_render_agent.py`
- `src/sase/ace/tui/widgets/_agent_list_styling.py`

Relevant test and snapshot areas:

- `tests/ace/tui/widgets/test_agent_list_runtime_rendering.py`
- `tests/ace/tui/widgets/test_agent_display_list_rendering.py`
- Agents-tab visual snapshots under `tests/ace/tui/visual/snapshots/png/`
- The populated tools-panel visual snapshot, because it renders through the Agents tab list fixture

## Goals

1. In the Agents tab list rows, render persisted agent names as a bare trailing annotation, e.g. ` coder`, not
   ` [coder]`.
2. Keep the existing gold/yellow annotation style (`#FFD700`) so the name still has a visual distinction from status,
   tags, bead badges, and the display name.
3. Preserve the current metadata header behavior: `Name: coder`, not `Name: @coder` and not `Name: [coder]`.
4. Preserve bead derivation, grouping, sorting, render cache keys, prompt/file-reference `@` handling, and all unrelated
   bracketed UI markers.

## Design

Make a presentation-only change in the list row formatter:

- Change the agent-name append from ` [{agent.agent_name}]` to ` {agent.agent_name}`.
- Continue applying `_AGENT_NAME_ANNOTATION_STYLE` to the appended agent-name text.

Keep the shared `_AGENT_NAME_ANNOTATION_STYLE` constant because it is still useful for keeping the list annotation and
metadata `Name:` value visually aligned. Update the nearby comment so it no longer documents a bracketed list
annotation.

Do not change:

- `agent.agent_name` storage or normalization.
- Bead-id derivation from agent names.
- The metadata header renderer beyond any comment import cleanup that proves necessary.
- Other `@name` renderings in modals/toasts/actions.
- Other bracketed markers such as `[a]`, `[✓]`, `[agent]`, status summaries, or file/artifact hints.

## Test Plan

Focused unit tests:

- Update `test_format_agent_option_keeps_tag_badge_and_agent_name_prefixes_distinct` to expect a bare ` coder`
  annotation, reject ` [coder]`, and keep tag labels as ` #fix`.
- Update bead/list rendering tests to expect strings like `◆ sase-x.3`, `◆ sase-x.land`, and `(RUNNING)×3 ◆ sase-x.3`.
- Keep metadata tests unchanged except for any assertions that indirectly mention list-row bracket syntax; `Name: name`
  should remain the expected metadata output.

Visual tests:

- Run the focused Agents-tab PNG snapshot tests and inspect any diffs. Expected diffs are text-width shifts from
  ` [name]` to ` name` in list rows only.
- Include the populated tools-panel visual test because it renders an Agents-tab list row with `agent_name="tools"`.
- Regenerate PNG goldens only when the diffs are limited to this intended list-row text change.

Repo verification:

- Run targeted widget tests for the updated formatter expectations.
- Run the relevant visual subset, then the full visual suite if the subset touches shared fixtures.
- Run `just check` before finishing, after source/test/golden changes are made.

## Risks and Mitigations

- **Ambiguity with other row text:** A bare name is less visually delimited than `[name]`. Keep the gold style and the
  existing placement after status/fold/bead annotations so the row still separates tag labels (`#tag`) from agent-name
  annotations.
- **Over-broad bracket removal:** There are many unrelated square-bracket conventions in the TUI. Limit the source edit
  to the trailing `agent.agent_name` annotation in `_agent_list_render_agent.py`.
- **Snapshot churn:** Removing two cells per named row can shift right-aligned suffixes and visual snapshot pixels. Use
  existing PNG snapshot tests to verify that shifts are limited to expected row text/layout movement.
- **Accidental metadata rollback:** The previous metadata cleanup should be preserved. Keep tests asserting
  `Name: reviewer` and the gold metadata span.
