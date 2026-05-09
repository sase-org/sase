---
create_time: 2026-05-09 17:36:43
status: done
prompt: sdd/prompts/202605/agent_panel_count_colors.md
---
# Plan: Agent Panel Count Colors

## Goal

The Agents tab dynamic panel titles already show the right shorthand status counts, for example:

```text
#apple · 2 [H1 R1]
```

The bracket characters and shorthand letters should render in the same white/grey style used by the total panel count
(` · 2`). The status count numbers can keep their semantic per-status colors.

## Current Rendering Path

Panel titles are built by `src/sase/ace/tui/actions/agents/_display_panels.py` in `_agent_panel_border_title()`.

The current code appends:

- panel label with tag/untagged/all-agents styling
- total count with `_PANEL_COUNT_STYLE`
- shorthand metrics where `" ["`, spaces, letters, and `"]"` use `"dim"`
- metric numbers use `_PANEL_METRIC_STYLES[name]`

Tests for this surface live in `tests/ace/tui/test_agent_panel_titles.py`.

## Implementation Approach

1. Keep `_PANEL_COUNT_STYLE` as the single source of truth for the neutral title count color.
2. Change only the shorthand metrics punctuation and label-letter style in `_agent_panel_border_title()` from `"dim"` to
   `_PANEL_COUNT_STYLE`.
3. Leave `_PANEL_METRIC_STYLES` untouched so the count digits remain status-colored.
4. Extend the panel-title tests to assert the bracket/letter spans use `_PANEL_COUNT_STYLE` and the count digits still
   use their status-specific styles.

## Verification

Run the focused title test:

```bash
pytest tests/ace/tui/test_agent_panel_titles.py
```

Because this repo requires a full check after source changes, also run:

```bash
just install
just check
```

If `just check` is unavailable or fails for an environment issue, capture the concrete failure.
