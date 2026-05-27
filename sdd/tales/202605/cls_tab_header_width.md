---
create_time: 2026-05-27 07:00:57
status: done
prompt: sdd/prompts/202605/cls_tab_header_width.md
---
# Plan: Bound CLs Tab Group Headers to the Left Side Panel

## Context

The CLs tab renders grouped ChangeSpec rows through `ChangeSpecList` and `_changespec_list_render.render_grouped`. Group
headers are formatted by `_changespec_list_banner.format_changespec_banner_option`.

Today the grouped renderer sizes banner rows from the widest ChangeSpec row:

- `max_cs_width` includes full ChangeSpec names and CL URLs.
- `banner_width = max(CS_MIN_BANNER_WIDTH, max_cs_width, max_banner_natural)`.
- The parent `#list-container` then clamps the side panel to `_MAX_LIST_WIDTH` (`80` cells).

That mismatch lets a very long ChangeSpec row create a banner prompt wider than the side panel. Textual wraps the banner
rule and `N CLs` chip onto another visual line, which is the overflow shown in the snapshot.

## Goals

- Group header rows must render as a single line whose prompt is no wider than the CLs left side-panel can display.
- The `N CLs` chip should remain visible whenever the normal panel width leaves room for it.
- Long group labels should degrade by truncating the label, not by wrapping the header or pushing the chip past the
  panel.
- Long ChangeSpec rows should still be allowed to request a wider side-panel up to the existing panel max, but they must
  not force header rows past that max.

## Implementation

1. Add an explicit reusable CL list width contract for renderer-side content:
   - Keep the existing side-panel min/max behavior unchanged.
   - Introduce a maximum banner content width equal to the side-panel maximum minus the existing list content
     padding/border allowance.
   - Avoid importing `app.py` from widget render modules to prevent circular imports; use a small constants module or
     widget-local constants with clear comments.

2. Change `_changespec_list_banner.format_changespec_banner_option` so it can always fit a banner into the supplied
   width:
   - Measure cells with Rich/Text helpers rather than plain `len()` where it affects layout.
   - Compute the maximum label width after reserving space for hint, prefix, at least two rule cells, the gap, and the
     `N CLs` chip.
   - Truncate only the label with ellipsis when needed.
   - Keep the rule/chip suffix inside the requested width.

3. Change `_changespec_list_render.render_grouped` banner sizing:
   - Continue computing natural widths so the side panel still grows for normal labels and long rows.
   - Clamp only the emitted banner width to the maximum usable panel content width.
   - Keep `WidthChanged` behavior broad enough that long CL rows still request the parent container’s max width instead
     of shrinking the panel.

4. Add no-wrap protection for `ChangeSpecList` rows:
   - Match the existing Agents and AXE sidebars by setting `text-wrap: nowrap` and `text-overflow: clip` in
     `styles.tcss`.
   - Prefer preserving full row text internally while letting the viewport clip overlong CL rows.

## Tests

1. Update the direct grouped-render tests:
   - Replace the old assertion that a long CL name forces banner width to the full long row width.
   - Assert banner prompt cell length is bounded by the CL list max content width.
   - Assert the `N CLs` chip remains present after truncation.
   - Add a case with an overlong group label to prove label truncation keeps the rendered banner within width.

2. Add or update style coverage for mounted `ChangeSpecList`:
   - Assert `text_wrap == "nowrap"` and `text_overflow == "clip"`.
   - Assert narrow mounted rows keep one visual row per option, mirroring the existing Agents sidebar regression test.

3. Run focused tests first:
   - `pytest tests/ace/tui/widgets/test_changespec_list_grouped.py`
   - `pytest tests/ace/tui/widgets/test_changespec_list_single_line.py` if a new file is added.

4. Because this repo requires it after source changes, run:
   - `just install`
   - `just check`
