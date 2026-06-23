---
create_time: 2026-06-23 12:26:06
status: done
prompt: sdd/prompts/202606/fix_flaky_input_modal_error_snapshot.md
---
# Fix flaky `test_input_collection_modal_error_png_snapshot`

## Problem

CI (`just test-cov` / GitHub Actions) intermittently fails with:

```
FAILED tests/ace/tui/visual/test_ace_png_snapshots_inputs.py::test_input_collection_modal_error_png_snapshot
AssertionError: ACE PNG snapshot mismatch: .../input_collection_modal_error_120x40.png
Changed pixels: 52945/1520532 (3.482005%); allowed: no pixel cap and 0.100000% ($SASE_VISUAL_PNG_MAX_DIFF_RATIO)
```

The test passes locally on single runs but fails ~1-in-4 times. It is a genuinely flaky visual snapshot, not an
environment/font-drift problem.

## Root cause (confirmed by instrumented reproduction)

The error-state test does:

```python
modal.query_one("#field-input-0", Input).value = "billing"
modal.query_one("#field-input-1", Input).value = "three"   # invalid int
modal.query_one("#toggle-optional", Button).press()         # <-- the culprit
await wait_for_visual_idle(page)
ace_png_visual.assert_page_png(page, "input_collection_modal_error_120x40", ...)
```

Textual's `Button.press()` (see `textual/widgets/_button.py`) calls `_start_active_affect()`, which adds the transient
`-active` CSS class (the pressed / highlighted look) and schedules its removal **0.2s later** via
`set_timer(self.active_effect_duration, partial(self.remove_class, "-active"))`.

`wait_for_visual_idle()` only waits on the three detail debouncers and pumps the message queue a few times — it does
**not** settle this 0.2s button-press animation timer. So the SVG capture races the timer:

- ~68% of runs: capture happens while `-active` is still applied → matches the committed golden.
- ~32% of runs: the timer fires first, `-active` is removed → button renders in its resting state → 3.4% of pixels
  differ on the toggle-button row → exceeds the 0.1% CI tolerance → failure.

Reproduction (25 captures, fonts pinned exactly like the visual conftest) produced exactly two outputs, perfectly
correlated with the button class:

```
golden hash 61c9b39014dc  active=True   count=17   <== committed golden
       hash 3aee8580ef92  active=False  count=8     (the 3.44% diff that fails CI)
```

The rendered diff is a single horizontal band precisely over the `▼ 1 optional input` toggle button — confirming the
only thing changing is that button's pressed-highlight.

Two important consequences:

1. **The committed golden is itself wrong**: it snapshots a _transient animation frame_ (the button
   mid-press-highlight), which is not a meaningful resting state for the "error state, optional section revealed" intent
   the test documents.
2. **Scope is localized**: `test_ace_png_snapshots_inputs.py` is the only visual test that activates a `Button` (every
   other visual test uses keyboard `page.press(...)` navigation, which never adds `-active`). So only one golden is
   affected — but the bug class (snapshotting a button mid-press) should be prevented for all future tests.

## Fix

Make the snapshot settle point neutralize Textual's transient button press-highlight, then regenerate the one affected
golden to its stable resting state.

### 1. Harden the shared settle helper

In `tests/ace/tui/visual/_ace_png_snapshot_helpers.py`, inside `wait_for_visual_idle()`, after the debouncer-wait loop
and before the final `for _ in range(3): await page.pause()` settle loop, strip the transient `-active` class from every
`Button` across the screen stack:

```python
# Neutralize Textual's transient button press-highlight. Button.press()/
# action_press() add the `-active` class and remove it via a 0.2s timer; a
# snapshot taken after pressing a button otherwise races that timer and flakily
# captures the pressed-highlight frame.
from textual.widgets import Button

for screen in page.app.screen_stack:
    for button in screen.query(Button):
        button.remove_class("-active")
```

The trailing `await page.pause()` loop already present then flushes the style/refresh so the capture reflects the
resting state. This is:

- **Deterministic**: verified that with this neutralization, all 25 repeated captures produce one identical output
  (`3aee8580ef92`).
- **A no-op for every other test**: no other visual test activates a button, and `remove_class` on a class that isn't
  present is harmless.
- **The correct architectural home**: `wait_for_visual_idle` is the single "settle before snapshot" point all visual
  tests call; "settle transient button highlight" belongs next to "settle debouncers". This is presentation-only Textual
  test glue, so it stays in this repo (not the Rust core).

This change is preferred over a one-line tweak inside the single test because it kills the entire bug class: any future
visual snapshot that presses a button is automatically immune.

### 2. Regenerate the affected golden

Because the neutralized (resting, `-active`-free) capture differs from the current golden (which froze the
pressed-highlight frame), regenerate exactly one golden:

```bash
just test-visual -- \
  tests/ace/tui/visual/test_ace_png_snapshots_inputs.py::test_input_collection_modal_error_png_snapshot \
  --sase-update-visual-snapshots
```

This rewrites `tests/ace/tui/visual/snapshots/png/input_collection_modal_error_120x40.png` to the stable resting state.
Confirm via `git status` that this is the **only** golden that changes (the sibling
`test_input_collection_modal_png_snapshot` does not press a button and must stay byte-identical). Visually sanity-check
the regenerated PNG: it should look the same as before except the toggle button is no longer in its pressed-highlight
state.

## Verification

1. `just install` (ephemeral workspace may have stale deps).
2. Stability: run the previously-flaky test many times back-to-back; it must pass every time (it failed ~1/4 before):
   ```bash
   for i in $(seq 1 25); do \
     just test-visual -- \
       tests/ace/tui/visual/test_ace_png_snapshots_inputs.py::test_input_collection_modal_error_png_snapshot \
       || echo "FAIL $i"; done
   ```
   (Or run the focused test repeatedly under `SASE_VISUAL_PNG_MAX_DIFF_RATIO=0.001` to mirror the CI tolerance.)
3. Full visual suite stays green and no unexpected goldens changed:
   ```bash
   just test-visual
   git status --short   # expect only input_collection_modal_error_120x40.png + the two source files
   ```
4. `just check` (required for non-bead / non-research file changes).

## Files touched

- `tests/ace/tui/visual/_ace_png_snapshot_helpers.py` — neutralize `-active` in `wait_for_visual_idle`.
- `tests/ace/tui/visual/snapshots/png/input_collection_modal_error_120x40.png` — regenerated golden (resting state).

## Out of scope / explicitly not doing

- No change to `InputCollectionModal` production code — this is purely a test-determinism issue; the modal behaves
  correctly.
- Not loosening the CI diff tolerance — the 0.1% ratio is appropriate; the fix removes the non-determinism rather than
  hiding it behind a wider tolerance.
- Not editing the `test_input_collection_modal_error_png_snapshot` body — keeping the `Button.press()` call exercises
  the real press path, and the helper now makes it deterministic.
