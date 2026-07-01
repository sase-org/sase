---
create_time: 2026-07-01 05:56:54
status: done
---
# Remove Agents Total Label

## Context

The screenshot `.sase/home/tmp/screenshots/20260701_054850.png` shows the Agents tab info strip rendering the total
visible top-level agent count as `1 Agents`. The requested behavior is to render only the number, e.g. `1`, while
leaving the surrounding metrics and controls intact.

The relevant renderer is `AgentInfoPanel` in `src/sase/ace/tui/widgets/agent_info_panel.py`. Its non-loading render path
currently appends the total count and then the literal `" Agents"`. Focused tests in
`tests/ace/tui/widgets/test_agent_info_panel.py` and `tests/ace/tui/test_startup_loading_indicators.py` intentionally
assert the old prefix.

This is presentation-only TUI text, so it belongs in the existing Python widget code. No Rust core change is needed.

## Desired Behavior

- The normal Agents info strip starts with only the visible top-level agent count:
  - `1 [1 running] ...` instead of `1 Agents [1 running] ...`
  - `5 ...` instead of `5 Agents ...`
- The loading state remains `Agents: …`, because it is a label for an unknown/loading value rather than a displayed
  total count.
- Other uses of the word `Agents` remain unchanged, including the tab label, modal titles, onboarding text, saved group
  labels, group headers, and metric labels such as `running`, `waiting`, `done`, etc.

## Implementation Plan

1. Update `AgentInfoPanel._build_display_text` so the non-loading path renders the total count without appending the
   `" Agents"` label.
   - Keep the total count style unchanged.
   - Preserve the existing metric-strip behavior, so a nonzero metric list naturally follows as `12 [2 stopped ...]`.
   - Preserve the loading short-circuit that renders `Agents: …`.

2. Update focused widget tests to assert the new count prefix.
   - Rename or adjust `test_agent_count_strip_renders_total_before_agents_label` so it describes rendering only the
     numeric total before metrics.
   - Change expected strings from `12 Agents [...]`, `10 Agents [...]`, `9 Agents [...]`, and `5 Agents` to the
     corresponding number-only forms.
   - Keep assertions that guard against the old `Agents: 2/12` fraction-style display.

3. Update the startup-loading regression test for the cleared loading state.
   - Keep the loading assertion for `Agents: …`.
   - Change the cleared state assertion from `plain.startswith("5 Agents")` to a number-only equivalent.

4. Search for remaining focused assertions of the old `"<count> Agents"` info-strip wording and update only those tied
   to `AgentInfoPanel`.
   - Do not change unrelated `Agents` strings elsewhere in the TUI.

5. Validate with targeted tests first:
   - `pytest tests/ace/tui/widgets/test_agent_info_panel.py tests/ace/tui/test_startup_loading_indicators.py`

6. Because this repo requires full checks after code changes, run:
   - `just install`
   - `just check`

## Risks

- The count strip becomes shorter, which is the requested effect and should not disturb layout.
- Removing the label can make a bare zero or count less self-describing, but the tab context and adjacent metrics still
  identify it as the Agents info strip. The loading state keeps its explicit label for clarity while data is
  unavailable.
