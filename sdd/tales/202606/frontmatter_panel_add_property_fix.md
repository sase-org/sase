---
create_time: 2026-06-17 17:37:19
status: done
prompt: sdd/prompts/202606/frontmatter_panel_add_property_fix.md
---
# Fix: adding an xprompt property disappears a prompt pane and traps focus

## Problem

When the user opens the xprompt **Frontmatter Property Panel** (`g=`) above the prompt input stack and adds a new
property (the reported case: a local `xprompts` helper via the sub-form modal), two things go wrong at once:

1. **A prompt input pane "completely disappears."** With more than one prompt pane open, after the panel grows to show
   the new property, one of the panes is clipped off-screen and no longer rendered.
2. **Typing goes nowhere and `Ctrl+C` does nothing.** After the sub-form modal saves, keyboard focus stays trapped on
   the Frontmatter Panel. Keystrokes are silently reinterpreted as the panel's row-navigation/edit commands (or
   dropped), so nothing appears in the still-visible prompt pane. The user had to press `Ctrl+C` twice to tear down the
   whole bar to recover.

Both are real bugs with distinct root causes; they happened to fire together.

## Root cause analysis

### Cause A — focus trap after the sub-form saves (the "typing goes nowhere" symptom)

Adding a structured property (`xprompts` or `input`) routes through a sub-form modal:

`g=` → panel focused → `a` → `AddRequested` → host pushes `AddPropertyModal` → pick `xprompts` →
`FrontmatterPanel.begin_add("xprompts")` → `_add_structured_item` → `_open_xprompt_modal` → push `XPromptItemModal` → on
close, `_done(result)`.

In `src/sase/ace/tui/widgets/_frontmatter_panel_editing.py`, both `_open_xprompt_modal._done` (line ~195) and
`_open_input_modal._done` (line ~170) **always** call `self._return_focus()`, which ends with `self.focus()` —
re-focusing the panel itself (rows mode):

```python
def _return_focus(self) -> None:
    """Re-focus the panel for row navigation after a sub-form closes."""
    self._edit_mode = "rows"
    self._show_rows_only()
    self._clamp_selection()
    self._refresh()
    self.focus()            # <-- focus stays on the panel, not the prompt body
```

So after saving the property, focus is on the `FrontmatterPanel`. The panel's `on_key` (`frontmatter_panel.py`) consumes
`j/k/h/l/a/d/e/enter/R/g…` as navigation/edit commands and lets other keys fall through to no visible effect — exactly
the "I typed and nothing appeared, and I had to Ctrl+C out" behavior. The panel was designed to keep focus so the user
could add several properties in a row, but that is not what the user expects after authoring one property.

**Per Q1 (chosen: "Back to the prompt pane"):** after a sub-form **save**, focus should return to the active prompt
input pane so the user can keep typing immediately; the panel is re-opened with `g=` to add more.

### Cause B — a prompt pane is clipped off-screen (the "disappearing pane" symptom)

The bar auto-sizes itself in `src/sase/ace/tui/widgets/_prompt_input_bar_stack_rendering.py`. For a multi-pane stack it
calls `_apply_multi_pane_heights(max_height, panel_rows)`, which reserves vertical space for the overlay panels and the
per-pane separators:

```python
reserve = 2 + completion_rows + count          # bar border (2) + panels + 1 separator/pane
content_budget = max(count, max_height - reserve)
...
bar_height = min(reserve + sum(alloc), max_height)
```

`panel_rows` is fed from `_frontmatter_panel_reserved_rows()` → `FrontmatterPanel.reserved_height`
(`frontmatter_panel.py`):

```python
@property
def reserved_height(self) -> int:
    if self._edit_mode == "raw":
        return 12
    base = self._content_lines + 2     # content + round border (top/bottom)
    if self._edit_mode == "edit":
        return base + 3
    return base                         # rows mode: content + border ONLY
```

**The panel's 1-row bottom margin is never counted.** The CSS for `#frontmatter-panel` (`styles.tcss`) is
`border: round` (2 rows) **and** `margin: 0 0 1 0` (1 row bottom margin), so the panel's true laid-out footprint is
`content + 2 + 1`. `reserved_height` returns only `content + 2`.

This is provably the bug: the panel's two sibling overlay panels with the **identical** CSS (`border` +
`margin: 0 0 1 0`) both correctly reserve `line_count + 3`:

- `_prompt_input_bar_completion.py`: `self._completion_line_count = line_count + 3  # +3 for panel border + margin`
- `_prompt_input_bar_g_prefix_hints.py`: `self._g_prefix_hints_line_count = line_count + 3`

Only the Frontmatter Panel uses `+2`, dropping the margin row. The consequence is a 1-row undercount whenever the panel
is visible:

- `content_budget` is over-counted by 1, so the panes are allowed to allocate one row more than actually fits, and
- `bar_height` is sized one row short.

The `#prompt-stack` is a `Vertical` with `height: 1fr`; the bar being one row short squeezes the stack region while the
panes carry explicit `styles.height`, so the overflow is clipped at the bottom of the stack — one pane "disappears."
(The same undercount also slightly clips the solo text area in single-pane mode, but with no separate pane to vanish it
goes unnoticed.)

**Per Q2 (chosen: "Full fix"):** correct the reserved-height accounting (the missing margin row) **and** make the stack
keep the active pane visible when the panel + panes still exceed the available height on very short terminals with many
panes.

## Fix plan

### 1. Return focus to the prompt body after a sub-form save (Cause A)

In `src/sase/ace/tui/widgets/_frontmatter_panel_editing.py`:

- Add a small helper that restores the rows view and then hands focus back to the body by posting the existing `Closed`
  message (the host already handles it; with a non-empty model — guaranteed right after a successful save — the panel
  **stays visible** and the body is focused in insert mode):

  ```python
  def _commit_to_body(self) -> None:
      """After a sub-form saves, restore the rows view and hand focus to the
      prompt body (the bar keeps the now-non-empty panel visible)."""
      self._edit_mode = "rows"
      self._show_rows_only()
      self._clamp_selection()
      self._refresh()
      self._close()   # posts Closed(is_empty=False) -> host focuses active pane
  ```

- In both `_open_input_modal._done` and `_open_xprompt_modal._done`: on a successful save (result is not None) call
  `self._commit_to_body()`; on **cancel** keep the current `self._return_focus()` (the user explicitly opened the panel
  and aborted, so staying in the panel is least surprising).

Why reuse `Closed`: the host's `on_frontmatter_panel_closed` already focuses `active_text_area()`, enters insert mode,
and only hides/drops the panel when the model is empty. After a real save the model is never empty, so the panel remains
visible (showing the just-added property) and the user is dropped straight back into typing — matching the chosen Q1
behavior with no new host wiring and no new message type. `g=` re-focuses the still-visible panel to add more.

- **Out of scope but noted:** adding a _scalar_ property via the inline editor (`_finish_inline_edit` → `self.focus()`)
  still returns to the panel. That editing happens visibly _inside_ the panel, so it is far less confusing than the
  modal case, and Q1 scoped the change to the sub-form modal. Left as-is; called out here for awareness.

### 2. Count the panel's bottom margin in `reserved_height` (Cause B, accounting)

In `src/sase/ace/tui/widgets/frontmatter_panel.py`, add the missing 1-row bottom margin so the panel reserves its true
footprint, matching the `+3` (border + margin) convention its sibling overlay panels already use:

```python
@property
def reserved_height(self) -> int:
    """Rows the panel occupies above the stack: content + round border + the
    1-row bottom margin (CSS ``margin: 0 0 1 0``), matching the completion /
    g-prefix panels' ``+3`` border+margin reservation so the bar never squeezes
    the prompt stack."""
    bottom_margin = 1
    if self._edit_mode == "raw":
        return 12 + bottom_margin
    base = self._content_lines + 2
    if self._edit_mode == "edit":
        return base + 3 + bottom_margin
    return base + bottom_margin
```

The margin applies in every mode (it is the panel's margin, not mode-specific), so it is added uniformly. This single
change fixes the reported rows-mode clip and the (latent) single-pane and edit/raw undercounts of the margin row.

- **Noted, not changed:** raw mode's flat `12` may also under-count the panel's own border, and edit mode does not count
  the inline `Input`'s 1-row top margin. These are separate, unreported latent off-by-ones outside the stated scope; the
  margin fix above is the targeted correction.

### 3. Keep the active pane visible when content still overflows (Cause B, robustness)

Even with correct accounting, a very short terminal with many panes can leave `reserve` larger than the screen, so the
bar caps at `max_height` and the explicitly-sized panes overflow the stack region. Guarantee the **active** pane is
never the one rendered off-screen:

- In `styles.tcss`, make `#prompt-stack` scrollable only when it overflows: add `overflow-y: auto` (and a minimal
  `scrollbar-size-vertical: 1`) to `PromptInputBar #prompt-stack`. When everything fits (the common case, including
  after fix #2) no scrollbar appears and nothing changes.
- In `_prompt_input_bar_stack_rendering.py`, after `_apply_multi_pane_heights` applies the pane heights, scroll the
  active pane into view: `self.active_text_area().scroll_visible(animate=False)` (guarded). The second, post-refresh
  `_update_height` pass ensures it lands after layout settles.

This keeps the focused pane on-screen (and its still-clipped neighbors reachable by scrolling) rather than silently
vanishing, on the pathological short-terminal/many-pane case.

`#prompt-stack` stays a `Vertical` (only its overflow style changes), so the existing
`query_one("#prompt-stack", Vertical)` lookups and all other layout behavior are unaffected.

## Testing

- `tests/ace/tui/widgets/test_frontmatter_panel_subeditors.py` — add: after saving an `xprompts` helper (and an `input`)
  via the sub-form modal, focus lands on the active `PromptTextArea` (body), the panel remains visible, and the body is
  in insert mode; after **cancelling** the modal, focus stays on the panel. Extends the existing modal-flow scaffolding
  in this file.
- `tests/ace/tui/widgets/test_prompt_input_bar_stack.py` — add a height test mirroring
  `test_stack_height_capped_by_terminal_and_active_grows`: with a multi-pane stack **and the frontmatter panel
  visible**, assert `reserve + sum(pane heights) <= bar height <= screen − 2` (i.e. no pane is clipped) and that the
  active pane is allocated room. Add/adjust a `reserved_height` assertion to pin the margin row (rows mode ==
  `content + 3`).
- `tests/ace/tui/widgets/test_frontmatter_panel.py` — add a focused `reserved_height` unit assertion for rows mode
  covering the bottom-margin row.
- Visual snapshots: the +1 row may shift `test_ace_png_snapshots_frontmatter_panel.py` /
  `test_ace_png_snapshots_prompt_stack.py` goldens for panel-visible cases. Re-generate intentional changes with
  `just test-visual --sase-update-visual-snapshots` and review the diffs.
- Run `just check` (after `just install`) before completion.

## Files touched

- `src/sase/ace/tui/widgets/_frontmatter_panel_editing.py` — focus-to-body on sub-form save.
- `src/sase/ace/tui/widgets/frontmatter_panel.py` — `reserved_height` counts the bottom margin.
- `src/sase/ace/tui/widgets/_prompt_input_bar_stack_rendering.py` — scroll active pane into view.
- `src/sase/ace/tui/styles.tcss` — `#prompt-stack` overflow/scrollbar.
- Tests as above.

## Out of scope

- Inline scalar-add returning to the body (noted in §1).
- Raw-mode border and edit-mode inline top-margin undercounts (noted in §2).
- Any change to how `g=` opens/toggles the panel or to the add-property picker flow itself.
