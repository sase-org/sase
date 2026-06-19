---
create_time: 2026-06-19 19:04:02
status: done
prompt: sdd/prompts/202606/completion_panel_excess_height.md
---
# Fix: xprompt completion menu inflates prompt input height

## Problem

When the xprompt completion menu auto-opens (the `#+` VCS project/PR completion and the auto-open `#…` xprompt menu
added today), the `sase ace` prompt input bar **grows taller than it needs to**. The extra blank rows then shrink away
as the user types into the xprompt token. See `.sase/home/tmp/screenshots/20260619_184705.png` and
`20260619_184722.png`.

Two qualities of the symptom are the key clues:

- It happens **"sometimes"** — only when the candidate list is long. The auto-open paths open with the _full,
  unfiltered_ list (every active project + PR for `#+`; every matching xprompt for `#f…`), which is commonly long.
- The excess **"goes away as I type in the xprompt"** — typing filters the list down, which shrinks it back to a correct
  size.

## Root cause (confirmed empirically)

The bar reserves vertical space for the completion popup through an integer field `_completion_line_count`. It is
computed in **three** places in `src/sase/ace/tui/widgets/_prompt_input_bar_completion.py` as:

```python
line_count = len(content.plain.splitlines()) if content.plain else 0
self._completion_line_count = line_count + 3   # +3 = 2 border rows + 1 bottom margin
```

(`show_file_completions` line ~167, `show_xprompt_arg_hint` line ~362, `show_jinja_diagnostics` line ~399.)

`_update_height()` / `_apply_multi_pane_heights()` in `src/sase/ace/tui/widgets/_prompt_input_bar_stack_rendering.py`
then add this value to the bar height.

**The bug:** `line_count + 3` ignores the panel's CSS cap. The `#prompt-completion` panel in
`src/sase/ace/tui/styles.tcss` has `max-height: 10` (and `max-height: 5` for the `.jinja-diagnostics` variant). When the
candidate list is long enough that the panel's border-box (content + 2 border rows) would exceed `max-height`, Textual
**clips** the panel to a 10-row border-box (8 visible content rows) + 1 margin = **11 rows of real footprint** — but the
bar still reserves `line_count + 3` rows. The difference is empty space at the bottom of the bar.

Verified by mounting `PromptInputBar` with the real `styles.tcss` loaded and measuring the compositor's painted panel
region vs. the reserved value:

| content lines | painted footprint (border-box + margin) | reserved `_completion_line_count` | excess blank rows |
| ------------- | --------------------------------------- | --------------------------------- | ----------------- |
| 3             | 6                                       | 6                                 | 0                 |
| 8             | 11                                      | 11                                | 0                 |
| 9             | 11                                      | 12                                | **1**             |
| 11            | 11                                      | 14                                | **3**             |
| 25            | 11                                      | 14                                | **3**             |

The excess appears exactly when content rows ≥ 9 (i.e. `line_count + 2 > 10`), which is why it only shows up for long
lists and disappears as filtering shrinks the list below the cap. The formula is otherwise exact, which is why short
menus are unaffected.

The same `_completion_line_count` feeds both the single-pane and multi-pane height paths, so there is a single point to
fix.

## Fix

Clamp the reserved rows to the panel's CSS `max-height` so the reservation always equals the real painted footprint.
Introduce a small shared helper (mirroring the CSS) in `_prompt_input_bar_completion.py` and use it at all three call
sites:

```python
# Mirror styles.tcss #prompt-completion: a solid border (top+bottom rows) and a
# one-row bottom margin frame the panel, and its height is capped by max-height.
# Keep these constants in sync with the CSS (a regression test enforces parity).
_PANEL_BORDER_ROWS = 2
_PANEL_MARGIN_ROWS = 1
_COMPLETION_PANEL_MAX_HEIGHT = 10   # #prompt-completion max-height
_JINJA_PANEL_MAX_HEIGHT = 5         # #prompt-completion.jinja-diagnostics max-height


def _reserved_panel_rows(line_count: int, max_height: int = _COMPLETION_PANEL_MAX_HEIGHT) -> int:
    """Rows the completion panel occupies in the bar, clamped to its CSS max-height."""
    border_box = min(line_count + _PANEL_BORDER_ROWS, max_height)
    return border_box + _PANEL_MARGIN_ROWS
```

Call sites:

- `show_file_completions`: `self._completion_line_count = _reserved_panel_rows(line_count)`
- `show_xprompt_arg_hint`: `self._completion_line_count = _reserved_panel_rows(line_count)`
- `show_jinja_diagnostics`: `self._completion_line_count = _reserved_panel_rows(line_count, _JINJA_PANEL_MAX_HEIGHT)`

This is presentation-only Textual layout glue, so it stays in this repo (no Rust-core boundary crossing per
`memory/rust_core_backend_boundary.md`). It is synchronous and adds no extra refresh pass, consistent with the TUI-perf
guidance to avoid new layout churn.

## Tests

Add a regression test (e.g. `tests/ace/tui/widgets/test_prompt_completion_height.py`) that mounts a `PromptInputBar` in
an app which loads the **real** `styles.tcss` (set `CSS_PATH` to the stylesheet, as `AceApp` does) so `max-height`
actually applies:

- Open `show_file_completions` with a **long** list (e.g. 15 rows) and assert there is **no excess blank space**: read
  the painted panel region from the compositor and assert `bar._completion_line_count == painted_border_box_height + 1`
  (margin), and that `bar.styles.height == text_visual_lines + 2 + bar._completion_line_count`.
- Open with a **short** list (3 rows) and assert the value is unchanged from today (no regression for the common case).

This test ties the Python constants to the CSS: if either the CSS `max-height` or the constant drifts, the painted
footprint and the reserved value diverge and the test fails.

Existing tests that are expected to keep passing as-is:

- `tests/ace/tui/widgets/test_prompt_virtual_wrap.py::test_wrapped_prompt_height_includes_completion_panel` sets
  `_completion_line_count` manually (4) — bypasses the changed code, unaffected.
- Visual PNG snapshots (`test_ace_png_snapshots_prompt_stack.py`, `test_ace_png_snapshots_vcs_project_completion.py`)
  both render 3-row completion lists — below the clamp threshold, so no golden regeneration is expected.

## Out of scope (noted, not fixed here)

With `max-height: 10` only 8 content rows are visible, yet the code slices `MAX_VISIBLE = 10` rows plus a `↓ N more…`
line, so for long lists ~2 candidate rows and the "more" indicator are silently clipped off the bottom. This is a
**separate, pre-existing** issue (opposite direction: too little shown, not too much height) and the primary fix does
not make it worse. Reconciling the visible slice with the real 8-row capacity would touch `MAX_VISIBLE`/scroll math and
the "more" counts. **Recommendation: defer** to a focused follow-up rather than bundle it with this height fix. Flagged
as a decision point for review.

## Verification steps

1. `just install` (ephemeral workspace), then `just check` (ruff + mypy + pytest). New regression test passes; no
   snapshot regeneration expected.
2. Manual: launch `sase ace`, trigger `#+` with many active projects/PRs (or a broad `#…` xprompt list). The bar should
   size to the capped menu with **no trailing blank rows**, and remain stable (no shrink-as-you-type artifact) while
   filtering.

## Files touched

- `src/sase/ace/tui/widgets/_prompt_input_bar_completion.py` — add helper + constants, use at 3 call sites.
- `tests/ace/tui/widgets/test_prompt_completion_height.py` — new regression test (real CSS loaded).
