---
create_time: 2026-06-29 09:23:43
status: done
prompt: sdd/prompts/202606/updates_tab_plugin_detail_space_and_scroll.md
---
# Plan: Updates tab — reclaim plugin-detail space and add `ctrl+d/u` scrolling

## Problem

On the **Updates** tab of the SASE Admin Center, the selected plugin's detail box (bottom-right) frequently shows only
part of its contents, with a scrollbar appearing even for short, simple plugins. The user wants two things:

1. Use the available space better so the scrollbar is **not necessary most of the time**.
2. When the content genuinely overflows, be able to **scroll the detail box with the `<ctrl+d>` / `<ctrl+u>` keymaps**.

## Root-cause analysis

The Updates tab is implemented by `PluginsBrowserPane` (`src/sase/ace/tui/modals/plugins_browser_pane.py`) with
rendering helpers in `src/sase/ace/tui/modals/plugins_browser_rendering.py`, hosted by `ConfigCenterModal`
(`config_center_modal.py`). Two distinct issues combine to produce the symptom:

### A. A redundant double border wastes vertical space

The detail area is a `VerticalScroll(id="plugins-detail-scroll")` holding a single `Static(id="plugins-detail")`. Its
CSS (in `src/sase/ace/tui/styles.tcss`) draws its own frame:

```tcss
PluginsBrowserPane #plugins-detail-scroll {
    height: 1fr;
    border: solid $secondary;   /* outer cyan box */
    padding: 0 1;
}
```

But the content placed inside it is already a fully-bordered, **titled** Rich `Panel` produced by `build_detail_panel()`
(`src/sase/plugins/render_catalog.py`), with a color-coded border (built-in green / community color) and the
`github · sase-org/sase-github` title. So the box is rendered **twice**: the plain `$secondary` `VerticalScroll` border
on the outside and the informative colored panel border on the inside (clearly visible in the screenshot as a cyan box
wrapping a green panel).

The nested borders consume ~2 vertical rows (top + bottom) plus horizontal cells for no informational gain. For a
typical up-to-date plugin the detail content is only ~12 rows, but after subtracting the doubled chrome it no longer
fits the available height, so a scrollbar appears even though the content is short.

### B. The detail box cannot be scrolled from the keyboard

`PluginsBrowserPane` defines no scroll bindings or actions. The global app bindings (`src/sase/ace/tui/bindings.py`) map
`ctrl+d`/`ctrl+u` to `scroll_detail_down`/`scroll_detail_up`, but those target the main ChangeSpec/Agent detail panels
_behind_ the modal — pressing them on the Updates tab does nothing visible to the plugin detail. Separately,
`ConfigCenterModal.on_key` already forwards `g`/`G` to `action_scroll_to_top`/`action_scroll_to_bottom` on the active
pane, but `PluginsBrowserPane` does not implement those methods, so `g`/`G` also no-op there. As a result there is
currently **no** way to reveal the clipped portion of an overflowing detail box.

### Precedent

`LogsPane` (`src/sase/ace/tui/modals/logs_pane.py`) is a sibling Admin Center pane with the exact master/detail +
`VerticalScroll` shape we want. It already implements `ctrl+d`/`ctrl+u` half-page scrolling and `g`/`G` top/bottom over
its `#log-detail-scroll`, with matching tests in `tests/ace/tui/test_logs_pane.py`. This plan mirrors that pane so the
two stay consistent.

## Goals

- The plugin detail box fits without a scrollbar for the common case (a plugin with no/few incoming commits) at the
  standard modal size.
- `ctrl+d` / `ctrl+u` scroll the detail box by half a page when content overflows (e.g. a plugin with many incoming
  commits, or a community warning + long description), with focus remaining on the plugin list.
- `g` / `G` jump the detail box to top / bottom (complementary; activates the forwarding `ConfigCenterModal` already
  wires up).
- The plugin list selection is never disturbed by detail scrolling.
- This is a presentation-only TUI change (layout, keybindings, scroll glue); no Rust core / wire changes are involved.

## Non-goals

- No change to `build_detail_panel()` itself — it is shared with the CLI `sase plugin show` for visual parity, so the
  colored, titled inner panel stays.
- No change to the SASE Core summary panel or the incoming-commits feature.
- No change to plugin install/update/uninstall behavior.

## Proposed approach

### 1. Reclaim space: drop the redundant outer frame on the detail scroller

In `src/sase/ace/tui/styles.tcss`, change `PluginsBrowserPane #plugins-detail-scroll` so the inner colored, titled
`build_detail_panel` becomes the visible box:

- Remove the outer `border: solid $secondary` (the inner Rich panel already supplies a better, color-coded, titled
  border).
- Drop the now-pointless `padding: 0 1` (the inner panel manages its own padding), reclaiming horizontal cells too.
- Keep the `VerticalScroll` widget and `height: 1fr` so scrolling still works when content genuinely overflows.

This reclaims the ~2 rows the doubled top/bottom border was eating, so a typical detail fits without a scrollbar. The
detail box top still aligns with the plugin list's bordered top, so the two columns stay visually balanced (the list
keeps its `$secondary` border; the detail shows its colored panel border).

Minor consideration: the no-selection placeholder (`"Select a plugin to view its details."`) currently sits inside the
outer border; without it the placeholder is plain text. The empty/no-selection state is rare (a row is highlighted on
load), so this is acceptable; if it reads poorly we can wrap the placeholder in a faint panel during implementation.

### 2. Add detail-scroll bindings + actions to `PluginsBrowserPane`

Mirror `LogsPane`. In `plugins_browser_pane.py`:

- Add to `BINDINGS`:
  - `("ctrl+d", "scroll_detail_down", "Scroll Down")`
  - `("ctrl+u", "scroll_detail_up", "Scroll Up")`
  - `("g", "scroll_to_top", "Top")`
  - `("G", "scroll_to_bottom", "Bottom")` and `("shift+g", "scroll_to_bottom", ...)`
- Add the action methods operating on `#plugins-detail-scroll` (`VerticalScroll`), reusing the half-page pattern from
  `LogsPane` (`scrollable_content_region.height // 2` for `ctrl+d/u`; `0` / `max_scroll_y` for `g`/`G`). Guard the
  lookups so an unmounted/absent scroller is a safe no-op.

Because these bindings live on the pane (closer in the DOM than the app-level bindings), they intercept
`ctrl+d`/`ctrl+u` before the events bubble to the app, so they act on the plugin detail rather than the hidden
ChangeSpec detail. Adding `action_scroll_to_top`/`action_scroll_to_bottom` also makes the `g`/`G` forwarding that
`ConfigCenterModal.on_key` already performs functional for this pane.

### 3. Surface the new keys in the hint line

`_hints()` (in `plugins_browser_rendering.py`) builds the footer hint string. Add a concise scroll hint (e.g.
`ctrl+d/u scroll`) consistent with `LogsPane`'s hint wording. The `#plugins-hints` row is `height: 1`, and the line is
already long when several conditional actions are present, so keep the addition terse and verify it still fits one line
at the standard width (abbreviate if needed). Per the Ace help-maintenance convention, also check the `?` help content /
any Updates-tab documentation references and update them if they enumerate the tab's keys.

### 4. Tests

- Add pane tests mirroring `tests/ace/tui/test_logs_pane.py`:
  - `BINDINGS` map `ctrl+d`/`ctrl+u`/`g`/`G` to the expected actions.
  - Driving a catalog whose detail genuinely overflows, `ctrl+d` increases `#plugins-detail-scroll.scroll_y` and
    `ctrl+u` decreases it; `G`/`g` reach `max_scroll_y` / `0`; and the highlighted plugin row is unchanged by scrolling.
  - A short-detail case asserts the box is not forced to scroll (e.g. `max_scroll_y == 0`) to lock in the space win and
    guard against regressions.
  - Place these alongside the existing `tests/ace/tui/test_plugins_browser_pane_detail.py` (reusing
    `_plugins_browser_pane_helpers.py`).

### 5. Visual snapshots

The CSS border/padding change alters the Updates-tab PNG goldens. After the change, re-run the visual suite and accept
the intentional diffs with `just test-visual ... --sase-update-visual-snapshots`, regenerating the affected
`config_center_plugins_*` snapshots (e.g. `config_center_plugins_tab`, `config_center_plugins_community_detail`,
`config_center_plugins_long_description`, `config_center_plugins_verbose`, `config_center_plugins_offline`,
`config_center_plugins_dev_update_available`, `config_center_updates_core_update_available`,
`config_center_plugins_empty`, `config_center_plugins_loading`, and the plugin-action preview snapshots if their detail
framing shifts). Inspect each regenerated golden to confirm the detail box now uses the single colored panel border and
that nothing else regressed.

## Files affected (expected)

- `src/sase/ace/tui/styles.tcss` — `#plugins-detail-scroll` border/padding.
- `src/sase/ace/tui/modals/plugins_browser_pane.py` — `BINDINGS` + scroll actions.
- `src/sase/ace/tui/modals/plugins_browser_rendering.py` — `_hints()` text.
- `tests/ace/tui/test_plugins_browser_pane_detail.py` (and helpers) — scroll tests.
- `tests/ace/tui/visual/snapshots/png/config_center_plugins_*.png` — regenerated.

## Risks / edge cases

- **Hint overflow**: the hints row is one line (`height: 1`); the addition must not push it past the modal width. Keep
  it terse and verify.
- **Empty-state cosmetics**: the no-selection placeholder loses its surrounding border (see §1) — acceptable, revisit
  only if it reads poorly.
- **Binding interception**: confirm the pane's `ctrl+d`/`ctrl+u` fire while the plugin `OptionList` is focused (the
  established `j`/`k` bindings already prove this bubbling path works) and do not leak to the app's behind-modal detail.
- **No-overflow no-ops**: `ctrl+d`/`ctrl+u` and `g`/`G` must be harmless when the content fits (scroll offsets clamp to
  `[0, max_scroll_y]`).

## Verification

- `just check` (install first, per repo guidance), plus targeted
  `pytest tests/ace/tui/test_plugins_browser_pane_detail.py` and `tests/ace/tui/test_logs_pane.py` for parity.
- `just test-visual` to confirm the regenerated plugin goldens match.
- Manual: open the Admin Center Updates tab, confirm a typical plugin's detail shows without a scrollbar, then select a
  plugin with many incoming commits and confirm `ctrl+d`/`ctrl+u` scroll the detail and `g`/`G` jump to extremes while
  the list highlight stays put.
