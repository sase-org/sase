---
create_time: 2026-05-09 17:56:33
status: done
---
# Neutralize Agents Tab Total Count Styling

## Context

The Agents tab top info panel renders its leading total as a colored metric:

- `src/sase/ace/tui/widgets/agent_info_panel.py`
  - `_COUNT_STYLES["total"] = "bold #5FAFFF"`
  - `_update_display()` appends `self._visible_agent_count` with that `"total"` style before `" Agents"`.

Dynamic agent panel titles already use a neutral count style:

- `src/sase/ace/tui/actions/agents/_display_panels.py`
  - `_PANEL_COUNT_STYLE = "#AFAFAF"`
  - `_agent_panel_border_title()` appends ` · {agent_count}` using that neutral grey, while status-specific counts
    remain colored.

The requested behavior is to stop coloring the aggregate total at the start of the top Agents tab count strip, while
keeping the dynamic status metrics colored.

## Implementation Plan

1. Update `AgentInfoPanel` so the leading total count uses a neutral style instead of `_COUNT_STYLES["total"]`.
   - Prefer a local constant in `agent_info_panel.py`, e.g. `_TOTAL_COUNT_STYLE = "#AFAFAF"`, to mirror the dynamic
     panel count color without coupling the widget to the panel action module.
   - Remove the `"total"` entry from `_COUNT_STYLES` if it becomes unused, keeping `_COUNT_STYLES` scoped to
     status/actionable metric counts only.
   - Leave the `" Agents"` label styling unchanged unless the visual check shows it should also be neutralized; the
     prompt specifically calls out the total count at the start.

2. Update the existing widget test that asserts count styles.
   - `tests/ace/tui/widgets/test_agent_info_panel.py::test_agent_count_numbers_have_rich_styles` should expect the total
     segment style to be `#AFAFAF`.
   - Keep assertions for `asking`, `running`, `waiting`, `failed`, `unread`, and `read` unchanged so the test still
     protects the meaningful status colors.

3. Run focused verification first.
   - `just install` if the workspace environment is not already prepared.
   - `pytest tests/ace/tui/widgets/test_agent_info_panel.py`

4. Run repo validation required after code changes.
   - `just check`

## Non-Goals

- Do not change dynamic panel title rendering; it already has the desired neutral aggregate count behavior.
- Do not change tab-bar counts, notification indicators, status metric colors, or any ChangeSpec/CLI styling.
- Do not move presentation logic into Rust core; this is Textual/Rich rendering only.
