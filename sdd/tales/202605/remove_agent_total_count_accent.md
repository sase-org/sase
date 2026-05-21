---
create_time: 2026-05-21 18:53:03
status: done
---
# Plan: Remove the Agents total-count accent bar

## Goal

Remove the small blue vertical accent bar to the left of the total agent count in the `sase ace` Agents tab info panel,
while preserving the useful part of the previous emphasis change: the total count itself should remain visually stronger
than it was before.

The desired count line should move from:

```text
▎12 Agents [2 stopped · 5 running · 2 waiting · 1 failed · 3 unread]
```

to:

```text
12 Agents [2 stopped · 5 running · 2 waiting · 1 failed · 3 unread]
```

## Current state

The relevant widget is `src/sase/ace/tui/widgets/agent_info_panel.py`.

At the top of `AgentInfoPanel`, the current styles are:

```python
_TOTAL_COUNT_STYLE = "bold #FFFFFF"
_TOTAL_COUNT_ACCENT_STYLE = "bold #5FAFFF"
```

In `_build_display_text`, the non-loading branch starts the rendered Rich `Text` like this:

```python
text.append("▎", style=self._TOTAL_COUNT_ACCENT_STYLE)
text.append(f"{self._visible_agent_count}", style=self._TOTAL_COUNT_STYLE)
text.append(" Agents", style="bold #87D7FF")
```

The loading state is separate and should remain unchanged:

```python
if self._loading:
    text.append("Agents", style="bold #87D7FF")
    text.append(": ", style="bold #87D7FF")
    text.append("…", style="dim italic")
    return text
```

## Design decision

Remove only the leading `▎` glyph and its style constant. Keep `_TOTAL_COUNT_STYLE = "bold #FFFFFF"` so the total count
still reads as the headline metric. This honors the user feedback precisely: the objection is to the little blue line,
not to the brighter count.

Do not replace the bar with another decorative glyph, separator, or filled badge. The resulting line should start
directly with the count, which is simpler and matches the user's requested removal.

## Implementation steps

1. Update `src/sase/ace/tui/widgets/agent_info_panel.py`.
   - Delete `_TOTAL_COUNT_ACCENT_STYLE = "bold #5FAFFF"`.
   - Delete the `text.append("▎", style=self._TOTAL_COUNT_ACCENT_STYLE)` call in `_build_display_text`.
   - Leave `_TOTAL_COUNT_STYLE = "bold #FFFFFF"` unchanged.
   - Leave the `" Agents"` label style unchanged.
   - Leave loading-state rendering unchanged.

2. Update unit tests that currently assert the leading accent in plain text.
   - In `tests/ace/tui/widgets/test_agent_info_panel.py`, update these expectations:
     - `test_agent_count_strip_renders_total_before_agents_label`: prefix should start with `"12 Agents ..."` instead of
       `"▎12 Agents ..."`.
     - `test_agent_count_strip_reports_starting_separately`: prefix should start with `"12 Agents ..."` instead of
       `"▎12 Agents ..."`.
     - `test_agent_count_strip_omits_zero_metric_types`: prefix should start with `"9 Agents ..."` instead of
       `"▎9 Agents ..."`.
     - `test_agent_count_strip_omits_metrics_section_when_all_counts_are_zero`: `counts_prefix` should equal
       `"5 Agents"` instead of `"▎5 Agents"`.
   - In `tests/ace/tui/test_startup_loading_indicators.py`, update `test_agent_info_panel_loading_clears` so the prefix
     is `"5 Agents"`.
   - Keep `test_agent_count_numbers_have_rich_styles` expecting `"total": "bold #FFFFFF"` because the count emphasis
     remains intentional.

3. Regenerate affected PNG visual snapshots.
   - The direct Agents-tab snapshots should change because the info panel loses one leading cell:
     - `tests/ace/tui/visual/snapshots/png/agents_list_120x40.png`
     - `tests/ace/tui/visual/snapshots/png/agents_selected_row_120x40.png`
     - `tests/ace/tui/visual/snapshots/png/agents_tools_panel_populated_120x40.png`
     - `tests/ace/tui/visual/snapshots/png/agents_unread_highlight_120x40.png`
   - The footer leader overflow snapshots may also change because they render the Agents tab info panel:
     - `tests/ace/tui/visual/snapshots/png/footer_leader_overflow_120x40.png`
     - `tests/ace/tui/visual/snapshots/png/footer_leader_overflow_80x30.png`
   - Use the existing visual workflow, likely:
     ```bash
     just test-visual -- --sase-update-visual-snapshots
     ```
     Then inspect the resulting snapshot changes to confirm the count line now starts directly with the number.

4. Verify the change.
   - Because this workspace may be stale, run `just install` before repository checks if dependencies are not already
     current.
   - Run focused tests while iterating:
     ```bash
     just test tests/ace/tui/widgets/test_agent_info_panel.py tests/ace/tui/test_startup_loading_indicators.py
     ```
   - Run the visual suite:
     ```bash
     just test-visual
     ```
   - Run the required full repository check before reporting completion:
     ```bash
     just check
     ```
   - If `just check` still reports the known pre-existing markdown formatting failures in `docs/ace.md` and
     `docs/rust_backend.md`, confirm they are unrelated to this change and report them separately.

## Files expected to change

- `src/sase/ace/tui/widgets/agent_info_panel.py`
- `tests/ace/tui/widgets/test_agent_info_panel.py`
- `tests/ace/tui/test_startup_loading_indicators.py`
- Any affected PNG goldens under `tests/ace/tui/visual/snapshots/png/`

## Out of scope

- Reverting the total count back to dim gray.
- Changing the ` Agents` label color.
- Changing status metric styles such as `starting`, `running`, `unread`, or `done`.
- Changing panel titles or per-group counts in `src/sase/ace/tui/actions/agents/_display_panel_titles.py`.
- Changing Rust core code; this is presentation-only TUI rendering.
