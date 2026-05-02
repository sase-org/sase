---
create_time: 2026-04-08 19:08:58
status: done
prompt: sdd/prompts/202604/fix_plotext_legend_crash.md
---

# Fix: plotext IndexError in telemetry dashboard charts mode

## Problem

`sase telemetry dashboard -c` crashes with `IndexError: list index out of range` inside plotext's internal legend
rendering code (`plotext/_build.py:261`).

## Root Cause

This is a bug in plotext's `build_plot()` method. The crash path:

1. `remove_outsiders()` (line 238) clips data points that fall outside the canvas bounds.
2. If ALL data points for a signal get clipped, `c[s]` (the color array for that signal) becomes empty.
3. The legend code uses `take_3 = lambda data: (data[:3] * 3)[:3]` to grab 3 colors. But `take_3([])` returns `[]`.
4. `color[s]` becomes `[ut.no_color]` — only 1 element instead of the expected 4.
5. The loop `for i in range(3)` tries `color[s][1]`, which triggers the `IndexError`.

This happens when a plotted signal has data but the canvas size/scale causes plotext to clip all its points. We can't
control plotext's internal clipping, so we need to defend against this at our call boundary.

## Fix

### Phase 1: Guard `plt.build()` against plotext internal errors (`charts.py`)

In both `render_line_chart` and `render_bar_chart`, wrap the `plt.build()` call in a try/except that catches
`IndexError` (and `ValueError` for good measure) and falls back to `_empty_panel`. This is the right boundary to defend
— we own the call into plotext and should handle its failure modes gracefully.

### Phase 2: Pre-filter empty series before plotting (`charts.py`)

In `render_line_chart`, skip the `plt.plot()` call for series that have no points **and also adjust the legend_labels
index accordingly**. Currently the code skips empty series in the loop body but still increments the enumeration index
`i`, so `legend_labels[i]` can pick the wrong label for subsequent series. Fix this by pre-filtering the series/labels
together before the loop, or by building a filtered list.

This reduces the likelihood of hitting the plotext bug by not asking plotext to render legend entries for phantom
series, but the Phase 1 guard is still needed since the bug can trigger even with non-empty series data that happens to
get clipped.
