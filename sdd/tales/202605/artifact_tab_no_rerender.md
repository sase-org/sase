---
create_time: 2026-05-15 14:59:01
status: done
prompt: sdd/prompts/202605/artifact_tab_no_rerender.md
---
# Plan: Stop re-rendering artifact pane PDF when `<tab>` returns focus to the TUI

## Problem

When the artifact viewer tmux pane is focused and the user presses `<tab>` to switch focus back to the SASE TUI, the
artifact (PDF, image, markdown render) is unnecessarily re-rendered in the tmux pane.

This is wasteful (especially for PDFs, where `kitten icat` re-uploads page images to the terminal) and produces a
visible flash/flicker in the pane that the user is no longer even looking at.

## Root Cause

In `src/sase/ace/tui/graphics/_viewer_loop.py`, both interactive loops (`run_artifact_page_loop` and
`run_artifact_sequence_loop`) treat `<tab>` as a normal loop iteration:

```python
# _viewer_loop.py, run_artifact_sequence_loop (~L226-231)
if key == _RETURN_TO_ACE_KEY and return_pane_id:
    select(return_pane_id)
    continue
```

The `continue` jumps back to the top of the `while True` loop, which then unconditionally:

1. Recomputes `current_area` (live `shutil.get_terminal_size`),
2. Calls `_clear_terminal(run)` — wipes the displayed image,
3. Re-prints the header panel,
4. Runs `kitten icat …` — re-displays the same page,
5. Reprints the page prompt,
6. Reads the next key.

Steps 2–5 are pure waste on a tab focus switch: the pane is now unfocused, its content is preserved by tmux until
something redraws it, and the user has not asked for any visual change.

The same pattern exists in `run_artifact_page_loop` at L134-137.

Note: PDF→PNG conversion itself is _not_ re-run — `page_cache` in the sequence loop (L167-182) is keyed by
`(index, columns, rows)` and hits unless the terminal resized. The visible "PDF re-renders" is the `kitten icat` redraw
(step 4), not the underlying rasterization. The plan fixes both — neither should happen on a tab focus switch.

## Goal

Pressing `<tab>` inside the artifact viewer should:

- Hand focus to the configured return pane (existing behavior).
- Leave the artifact pane's displayed contents untouched: **no clear, no header reprint, no icat redraw, no prompt
  reprint**.
- Continue waiting for the next keystroke on `stdin`. The next key (`j`, `k`, `n`, `p`, `r`, `q`) drives the next render
  exactly as today.

## Design

Restructure each loop so the **render phase** runs only when the current view state has changed since the last render.
Tab focus switching does not change view state.

Concrete approach: introduce a small `needs_render` flag (or, equivalently, split the loop body into a "render if
needed" block and a "read & dispatch" block).

Pseudocode for `run_artifact_sequence_loop`:

```python
needs_render = True
while True:
    current_area = image_area or artifact_image_area()
    if needs_render:
        rendered = pages_for(artifact_index, current_area)
        if rendered.warnings:
            return _PageLoopResult(returncode=1, warnings=rendered.warnings)
        pages = rendered.pages
        if not pages:
            return _PageLoopResult(returncode=1)
        _clear_terminal(run)
        _print_artifact_header(...)
        result = run(kitten_icat_command(pages[page_index], current_area))
        if result.returncode != 0:
            return _PageLoopResult(returncode=result.returncode)
        _move_cursor_below_image(current_area)
        print_page_prompt(...)
        needs_render = False

    available_keys = page_loop_available_keys(...)
    while (key := read()) not in available_keys:
        pass

    if key == "q":
        _clear_terminal(run)
        return _PageLoopResult()
    if key == _RETURN_TO_ACE_KEY and return_pane_id:
        select(return_pane_id)
        # Deliberately do NOT set needs_render=True — pane content is intact
        # and we are now unfocused. Next non-tab key will re-render.
        continue
    # All other keys change view state.
    needs_render = True
    if key in {"j", "k", "r"}:
        ...
    elif key == "n":
        ...
    elif key == "p":
        ...
```

The same shape applies to `run_artifact_page_loop`.

Subtleties:

- **`r` (refresh)** must still force a full render — easy, since `r` is a non-tab key and falls into the
  `needs_render = True` branch.
- **Repeated `<tab>` presses** from inside the pane (user toggles back and forth without doing anything else) should
  remain cheap — each press only re-runs `select_tmux_pane` and waits for input again. The existing `select_tmux_pane`
  is already idempotent.
- **Terminal resize while focus is on the TUI**: if the user resizes the outer terminal before returning focus and
  pressing a key, the cached image geometry may no longer match. This is already handled by `pages_for`'s cache key
  including `(columns, rows)` and by `current_area` being recomputed on every loop iteration. The next non-tab key
  recomputes `current_area` and re-renders correctly.
- **Suppressed prompt after tab**: the page prompt that was last printed before the tab press stays in the pane until
  the next render. That is the desired behavior — the pane is "frozen" while focus is elsewhere.

No changes are needed to `_viewer_launch.py`, the tab keymap on the TUI side (`actions/navigation/_basic.py`), or the
page-cache logic.

## Test Plan

Two existing tests encode the bug as expected behavior and will need to be updated:

1. `tests/ace/tui/artifact_viewer/test_loops.py::test_run_artifact_page_loop_tab_focuses_return_pane_and_stays_open`
   currently asserts:

   ```python
   commands == [
       ["clear"], _test_icat_command(page),
       ["clear"], _test_icat_command(page),  # ← redundant redraw after tab
       ["clear"],
   ]
   ```

   After the fix it should assert one initial render, no redraw on tab, and a final clear on quit:

   ```python
   commands == [
       ["clear"], _test_icat_command(page),
       ["clear"],
   ]
   ```

2. `tests/ace/tui/artifact_viewer/test_loops.py::test_run_artifact_sequence_loop_tab_focuses_return_pane_and_stays_open`
   needs the same adjustment.

New tests to add (same file):

- **Tab → j re-renders correctly**: keys `["\t", "j", "q"]` over a multi-page artifact should produce exactly two icat
  calls (page 1 initial, page 2 after `j`) with no extra render between `\t` and `j`. This locks in that suppressing the
  redraw on tab does not break the next real render.
- **Tab → r forces a refresh**: keys `["\t", "r", "q"]` should produce two icat calls of the same page (initial +
  refresh).
- **Multiple tabs are cheap**: keys `["\t", "\t", "q"]` should record two `select_pane` calls but only one icat call
  total.

Verification commands (run from the workspace dir):

```bash
just install
just check
```

## Out of Scope

- Persisting `page_cache` across viewer subprocess restarts.
- Changing PDF→PNG rasterization (still via `pdftoppm`).
- Tab keymap behavior on the TUI side (already correct; only the in-pane loop is wrong).
- Any change to footer/header content or layout.

## Files Touched

- `src/sase/ace/tui/graphics/_viewer_loop.py` — restructure both loops.
- `tests/ace/tui/artifact_viewer/test_loops.py` — update two existing tab tests, add three new ones.
