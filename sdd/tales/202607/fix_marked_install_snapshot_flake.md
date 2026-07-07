---
create_time: 2026-07-07 11:13:06
status: done
prompt: sdd/prompts/202607/fix_marked_install_snapshot_flake.md
---
# Fix flaky visual snapshot: `test_config_center_plugins_marked_install_png_snapshot`

## Problem

CI (`just test-cov`) intermittently fails on master with:

```
FAILED tests/ace/tui/visual/test_ace_png_snapshots_config_center_plugin_actions.py::test_config_center_plugins_marked_install_png_snapshot
Changed pixels: 36229/1520532 (2.382653%); allowed: no pixel cap and 1.000000% ($SASE_VISUAL_PNG_MAX_DIFF_RATIO)
```

The failure is intermittent: the same tree passed CI on the release-please PR run minutes after the master push run
failed, and the test passes locally.

## Root cause (confirmed by exact reproduction)

The test races the plugins pane's **debounced detail-panel repaint** (0.15 s timer):

1. The test highlights `nvim` and calls `pane.action_toggle_install_mark()`
   (`src/sase/ace/tui/modals/plugins_browser_install.py`).
2. The mark toggle calls `_advance_install_mark_selection()` (`src/sase/ace/tui/modals/plugins_browser_rendering.py`),
   which synchronously moves the list highlight to the next installable row — `acme`.
3. The highlight change fires `on_option_list_option_highlighted`, which schedules the detail-panel repaint through
   `pane._detail_debouncer` (`DetailPanelDebouncer`, `src/sase/ace/tui/util/debounce.py`, `DEFAULT_DEBOUNCE_S = 0.15`).
4. The test then waits only for `pane._marked_install == {"nvim"}` and `wait_for_visual_idle(page)`.
   `wait_for_visual_idle` (`tests/ace/tui/visual/_ace_png_snapshot_helpers.py`) checks the three **app-level**
   debouncers (`_changespec_detail_debouncer`, `_agent_detail_debouncer`, `_axe_detail_debouncer`) — it does **not**
   know about the plugins pane's own `_detail_debouncer`.
5. The snapshot therefore captures whichever state the 0.15 s timer happens to be in:
   - **Fast machine (the committed golden):** timer has not fired → detail panel still shows the initial `github` row.
   - **Slow/loaded CI runner:** timer fires before capture → detail panel repaints to `acme` (community-plugin warning
     banner + acme detail panel) → ~2.4 % of pixels differ, exceeding the 1 % CI tolerance.

**Proof:** forcing the debounce timer to fire almost immediately (a throwaway pytest plugin that shrinks
`DetailPanelDebouncer`'s delay to ~0, simulating a slow runner) reproduces the CI failure _exactly_ —
`Changed pixels: 36229/1520532 (2.382653%)`, byte-identical to the CI numbers — and the rendered `actual.png` shows the
detail panel on `acme` with the COMMUNITY PLUGIN warning, while the golden shows it frozen on `github`.

This test is the outlier: every test in `test_ace_png_snapshots_config_center_plugins.py` and the sibling
`test_config_center_plugins_install_preview_png_snapshot` already settle the debounced repaint deterministically
(`await page.wait_for(lambda _s: pane._detail_name == <row>)` + `_wait_for_plugins_detail(page, pane)`) before
snapshotting. The marked-install test (added with the batch-install feature) never got those waits, and — uniquely — its
highlighted row _changes as a side effect_ of the action under test, so a repaint is always in flight at capture time.

## Fix

Make the test wait for the settled post-toggle state, then re-capture the golden in that deterministic state. No product
code changes — the debounce is intended UX behavior.

### 1. `tests/ace/tui/visual/test_ace_png_snapshots_config_center_plugin_actions.py`

In `test_config_center_plugins_marked_install_png_snapshot`, after `pane.action_toggle_install_mark()` and the existing
`_marked_install == {"nvim"}` wait, adopt the established settle pattern used by the sibling tests:

- wait for `pane._detail_name == "acme"` (the mark toggle advances the highlight to the next installable row, `acme`;
  this wait guarantees the debounced repaint has landed on it), with a short comment explaining the advance-selection
  side effect;
- replace the bare `wait_for_visual_idle(page)` with `_wait_for_plugins_detail(page, pane)` (which waits for the
  debouncer to drain and then calls `wait_for_visual_idle` itself), importing it from
  `tests/ace/tui/visual/_ace_config_center_png_snapshot_helpers.py` alongside the existing imports.

The settled `acme` detail is itself deterministic: `acme` is not installed and has no update available, so
`plugin_entry_commit_spec` returns `None` and no async incoming-commits fetch (and no follow-up repaint) is triggered
for it.

### 2. Regenerate the golden

Re-capture `tests/ace/tui/visual/snapshots/png/config_center_plugins_marked_install_120x40.png` with
`--sase-update-visual-snapshots`. The new golden will show the settled end state: `[√]` mark on `nvim`, highlight on
`acme`, `i install (1)` hints line, and the detail panel on `acme` (community warning + panel) instead of the
mid-transition `github` detail.

## Verification

1. Run the test repeatedly (~10×) at the normal 0.15 s debounce — must pass every run (local runs use exact pixel
   equality, stricter than CI).
2. Re-run the slow-runner simulation (near-zero debounce delay via the throwaway plugin) — must now also pass, since the
   test waits for the exact state the golden encodes regardless of timer speed.
3. Run the rest of the plugins visual family (`test_ace_png_snapshots_config_center_plugin_actions.py`,
   `test_ace_png_snapshots_config_center_plugins.py`) to confirm no collateral golden drift.
4. `just check` before finishing, per repo policy.

## Explicitly out of scope

- Extending `wait_for_visual_idle` to discover pane-level debouncers generically: larger blast radius across every
  visual test for no additional determinism here; the per-test settle pattern is the established convention.
- The other confirm-preview tests (`update`/`uninstall`) highlight `github`, which is already the initially rendered
  detail row (their debounced repaint is a no-op), and their goldens capture a modal overlay; they do not exhibit this
  race.
