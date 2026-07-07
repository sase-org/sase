---
create_time: 2026-07-07 13:05:24
status: done
prompt: sdd/prompts/202607/merge_help_and_tab_guide_panels.md
---
# Merge the `?` Help panel and `,?` Tab Guide into one two-tab Help panel

## Problem & Product Context

The ace TUI currently has two separate discoverability surfaces that users must find independently:

- **`?` → `HelpModal`** (`src/sase/ace/tui/modals/help_modal/`): the keymap reference — boxed, two-column sections
  scoped to the active app tab (PRs / Agents / AXE).
- **`,?` → `TabGuideModal`** (`src/sase/ace/tui/modals/tab_guide_modal.py`): the in-depth onboarding guide/tour for the
  active app tab (hosts the `ChangeSpecOnboarding` / `AgentOnboarding` / `AxeOnboarding` widgets).

Both panels share almost all their chrome and behavior (`esc`/`q`/`?` close, `ctrl+d`/`ctrl+u` scroll, `tab`/`shift+tab`
switches the _app_ tab in place), yet they have different borders, titles, footers, and entry points. New users rarely
discover `,?` at all.

**Goal:** one Help panel, opened with `?`, containing two inner tabs — **Keymaps** (old `?` content) and **Guide** (old
`,?` content) — switched with `[` / `]`. The `,?` leader keymap is retired entirely.

## Design

### The one-glance mental model

> `?` opens Help. `[`/`]` moves between the panel's own tabs. `tab`/`shift+tab` still follows the app's tabs.
> `esc`/`q`/`?` closes.

This mirrors the SASE Admin Center (`#`) exactly: `ConfigCenterModal` already uses a clickable one-line tab strip with
`[` / `]` cycling (`config_center_modal.py`, `_ConfigCenterTabStrip`). Reusing that idiom means users learn the "panel
with inner tabs" pattern once and it works everywhere.

### Panel anatomy (top to bottom)

```
╭─────────────────────── (accent border follows app tab) ───────────────────────╮
│                            ✦ sase ace Help ✦                                  │
│                                Agents Tab                                     │
│                                                                               │
│                          Keymaps  │  Guide                                    │
│  ─────────────────────────────────────────────────────────────────────────   │
│                                                                               │
│   <active view: keymaps columns OR onboarding guide, in a ContentSwitcher>    │
│                                                                               │
│  ─────────────────────────────────────────────────────────────────────────   │
│     ? / q / esc close · [ / ] panel tabs · tab / shift+tab app tabs ·         │
│                            ctrl+d / ctrl+u scroll                             │
╰───────────────────────────────────────────────────────────────────────────────╯
```

1. **Header** — keep the existing star title (`✦ sase ace Help ✦`) and the app-tab context line ("PRs Tab" / "Agents
   Tab" / "Axe Tab").
2. **Tab strip** — a centered, clickable strip with the two inner tabs. Active label rendered bold in the current app
   tab's accent color, inactive label dim gray; separated by a `│` like the Admin Center strip. **No numbers** in this
   strip (unlike Admin Center) because digits `0`–`9` are already load-saved-query shortcuts inside the help panel —
   numbering the tabs would advertise a conflicting affordance.
3. **Content** — a Textual `ContentSwitcher` holding both views:
   - _Keymaps view_: the existing two-column boxed keymap content (`#help-columns` inside its `VerticalScroll`),
     unchanged.
   - _Guide view_: the per-tab onboarding widget, built exactly as `TabGuideModal._build_guide()` does today (including
     the agents launch-target/plugin state forwarding).
4. **Footer** — a single footer line (built from configured key display names, as `HelpModal._build_footer()` does now)
   that now also advertises `[` / `]`. The guide widgets' internal modal footers (built by `build_guide_footer()` in
   `widgets/_onboarding_common.py`) are removed — that text was modal chrome ("esc closes · … · ,? reopens anytime") and
   the panel footer now owns that job. This also kills the last `,?` reference.

### Visual identity

- The panel border adopts the **per-app-tab accent color** the Tab Guide modal uses today (`round #00D7AF` PRs /
  `#87D7FF` Agents / `#FF5F5F` AXE), replacing the Help modal's current `double $primary`. The whole panel then
  telegraphs which app tab it documents, and the accent also colors the active inner-tab label — one coherent color
  story per tab.
- Geometry: keep the Help modal's sizing (`width: 90%; max-width: 150; height: 85%`). The keymaps view's two 57-char
  columns dictate the minimum useful width; the guide view already centers its content (`align-horizontal: center`), so
  it looks right in the same container.

### Interaction rules

| Key                                                    | Behavior                                                                                                                          |
| ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| `?` (app keymap `show_help`)                           | Opens the panel; pressing `?` again closes it (both panels already close on `?` — keep the toggle feel).                          |
| `[` / `]`                                              | Cycle inner tabs with modulo wrapping (with two tabs, both act as "switch to the other tab"). Same actions the Admin Center uses. |
| `tab` / `shift+tab` (configured `next_tab`/`prev_tab`) | Switch the _app_ tab; panel refreshes in place on **both** inner views (existing behavior of both modals, preserved).             |
| `esc` / `q`                                            | Close.                                                                                                                            |
| `ctrl+d` / `ctrl+u`                                    | Half-page scroll of the _active_ view's scroll container.                                                                         |
| `0`–`9`, `^` / `_`                                     | Saved-query load and query-history navigation keep working panel-wide (they dismiss the panel and act), regardless of inner tab.  |
| Mouse                                                  | Clicking a tab-strip label switches inner tabs.                                                                                   |

- The panel **always opens on Keymaps**. `?` has years of "show me the keys" muscle memory; landing somewhere else
  depending on history would make the panel feel flaky. (Alternative — remembering the last inner tab like the Admin
  Center does — is deliberately rejected for this quick-reference popup.)
- `[` / `]` are hardcoded panel bindings, exactly like in `ConfigCenterModal` (they are not configurable there either;
  consistency wins). No conflict with the app-level `[`/`]` thinking-toggle bindings: modal bindings shadow app bindings
  while the panel is open.
- Copy mode continues to work from the panel (`CopyModeForwardingMixin` stays).

### Naming note (design decision surfaced for review)

The request named the second tab **"Tab Description"**. I recommend **"Guide"** instead: the codebase, hints, and
existing PNG goldens all call this content the _tab guide_ ("PRs Guide", "tab guide" footer hints), it is a tour rather
than a description, and inside a panel that itself has tabs, "Tab Description" reads ambiguously (which tabs?). The
label is a one-string change if you prefer "Tab Description" — say so on this plan and the implementation will use it.

## Architecture

### 1. Extract a shared clickable tab strip widget

Generalize `_ConfigCenterTabStrip` (currently private in `config_center_modal.py`) into a small reusable widget, e.g.
`src/sase/ace/tui/widgets/panel_tab_strip.py`:

- Parameterized by an ordered list of `(id, label, accent_color)` entries plus an optional "show numbers" flag (Admin
  Center: on; Help panel: off).
- Emits the same `TabClicked` message; keeps the width-aware click hit-testing.
- `ConfigCenterModal` switches to the shared widget with zero behavior change
  (`tests/ace/tui/test_config_center_tabs.py` guards this).

This is the reliability/beauty play: one tab-strip idiom, one implementation, consistent rendering across every tabbed
panel.

### 2. Merge the Guide view into the `help_modal` package

- `HelpModal` (keep the class name — app wiring, styles, and tests reference it) gains the inner-tab machinery: tab
  strip, `ContentSwitcher`, `[`/`]` actions, click handling, and a footer that reflects the new keys.
- Move the guide-building logic out of `tab_guide_modal.py` into the package (e.g. `help_modal/guide_view.py`): per-tab
  onboarding widget construction and the agents-state forwarding (`agents_launch_targets_available`,
  `agents_plugins_installed`), sourced from the app at open/refresh time the same way `_open_tab_guide_modal` sources
  them today.
- **Delete `TabGuideModal`** (`tab_guide_modal.py`, its export in `modals/__init__.py`, and its `#tab-guide-container`
  styles; fold what's needed into the help panel styles).
- `refresh_for_tab(...)` refreshes _everything_ in place on app-tab switch: title, both views (keymaps columns rebuilt;
  guide widget swapped for the new tab's widget), tab-strip accent, and border accent class. The `ContentSwitcher` makes
  the old `TabGuideModal.refresh_for_tab` node-removal workaround unnecessary.
- `app.py`'s tab-switch hook (currently two `isinstance` branches for `HelpModal` / `TabGuideModal`, `app.py:416`)
  collapses to one branch that also schedules the agents guide state prep when the new tab is `agents`.
- `action_show_help` (`actions/navigation/_modals.py`) now also calls the agents-guide state prep
  (`_prepare_agents_tab_guide_state`) on open, as `_open_tab_guide_modal` does today. That helper moves out of
  `LeaderModeMixin` (leader mode no longer owns any guide behavior) to the navigation modal mixin.

### 3. Retire the `,?` keymap everywhere

Remove `tab_guide` from the leader-mode keymap and every surface that reads or advertises it (a stale
`keys["tab_guide"]` read raises `KeyError`, so this sweep must be complete):

| Surface                                                | Change                                                                                                                                                            |
| ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `default_config.yml` (`leader_mode.keys.tab_guide`)    | Remove.                                                                                                                                                           |
| `keymaps/types.py` (`LeaderModeKeymaps` defaults)      | Remove.                                                                                                                                                           |
| `actions/agent_workflow/_leader_mode.py`               | Remove the `tab_guide` dispatch branch and `_open_tab_guide_modal`; relocate `_prepare_agents_tab_guide_state`.                                                   |
| `widgets/_keybinding_modes.py` (leader footer)         | Drop the `,? tab guide` entry.                                                                                                                                    |
| `help_modal/{changespecs,agents,axe}_bindings.py`      | Drop the leader-mode "Tab guide" row; add a `[ / ]` "Switch Keymaps / Guide" row to the General/Display section of each tab; keep the `?` row ("Show this help"). |
| `widgets/tab_quickstart.py`                            | Replace the `,?` row with the new affordance (e.g. keycaps `?` `]` — "The full tour of this tab: the in-depth guide.").                                           |
| `widgets/axe_info_panel.py` (`_append_tab_guide_hint`) | Point the persistent hint at the new path (`? ]  tab guide`-style keycaps).                                                                                       |
| `widgets/_onboarding_common.py` (`build_guide_footer`) | Remove, along with the onboarding widgets' internal footer sections — panel chrome owns the footer now.                                                           |

**Config compatibility:** the keymap loader warns-and-ignores unknown mode keys, so users with a `tab_guide` override in
`sase.yml` degrade gracefully to a logged warning — no startup failure. Pressing `,?` after this change hits the
existing "unknown leader key → exit mode silently" path.

**Transition affordance (recommended, cheap):** for one release, have the leader-mode dispatcher special-case an
unmatched `question_mark` with a toast — "Tab guide moved: press ? then ]" — so `,?` muscle memory retrains itself
instead of failing silently. Drop it later. (Skip if you'd rather not carry the special case; flagged for review.)

### Rust core boundary

This is presentation-only Textual work (modal layout, bindings, hints) — it stays entirely in this repo. No `sase-core`
changes.

## Test Plan

- **Unit / behavioral (update):**
  - `tests/ace/tui/modals/test_tab_guide_modal.py` → folds into help-panel tests: guide view built per app tab, agents
    state forwarded, `refresh_for_tab` rebuilds both views.
  - `tests/ace/tui/modals/test_help_modal.py` → keymaps view still rebuilt per tab; new: opens on Keymaps, `[`/`]` wrap,
    footer text.
  - `tests/ace/tui/test_popup_panel_tab_switch_keymaps.py` → rewrite the TabGuideModal case as `?` then `]`; keep
    configured `next_tab`/`prev_tab` coverage on both inner views.
  - `tests/ace/tui/test_leader_keymap_dispatch.py`, `test_leader_keybinding_footer.py`,
    `test_startup_loading_indicators.py`, `tests/test_keymaps_defaults.py`, `tests/test_keymaps_display_help.py`,
    `tests/ace/tui/widgets/test_tab_quickstart.py`, `test_axe_onboarding.py` (and sibling onboarding tests asserting the
    old footer) → drop/replace `tab_guide` expectations and hint strings.
  - `tests/ace/tui/test_config_center_tabs.py` → must stay green through the tab-strip extraction (no assertion changes
    expected).
- **New behavioral coverage:**
  - `[`/`]` and strip-click switch inner tabs; digits still load saved queries from the Guide tab; `?` toggles closed
    from either inner tab; border/strip accent classes follow the app tab.
- **PNG visual snapshots:**
  - Replace `tests/ace/tui/visual/test_ace_png_snapshots_tab_guide.py` and its `tab_guide_*_120x40.png` goldens with
    help-panel equivalents: one Guide-tab snapshot per app tab, plus at least one Keymaps-tab snapshot (that view has no
    golden today and is now first-class chrome).
  - Regenerate intentionally with `--sase-update-visual-snapshots`; inspect `.pytest_cache/sase-visual/` artifacts on
    any failure.

## Phases

1. **Extract the shared tab strip** — new `panel_tab_strip.py` widget; port `ConfigCenterModal` to it. Pure refactor,
   Admin Center pixel-identical.
2. **Build the two-tab Help panel** — inner tabs + `ContentSwitcher` + chrome in the `help_modal` package; guide view
   moved in; `TabGuideModal` deleted; `action_show_help` / `app.py` wiring updated; styles unified under the
   accent-border design.
3. **Retire `,?`** — keymap, dispatch, footer entry, and the full hint-surface sweep (table above), plus the optional
   transition toast.
4. **Tests & goldens** — update/extend the suites above; regenerate PNG goldens; `just check` clean.

Phases 2 and 3 must land together (removing the keymap while `TabGuideModal` still exists, or vice versa, leaves dead or
broken references); they are split only as implementation checkpoints.

## Verification

- `just install`, then `just lint`.
- Targeted pytest over the files in the Test Plan, then `just test-visual` (accept intentional golden changes), then
  full `just check`.
- Manual pass in `sase ace`: `?` on each app tab → Keymaps first; `]`/`[` and strip clicks; `tab`/`shift+tab` while on
  each inner tab; `esc`/`q`/`?` close; `,?` no longer opens anything (toast if the transition affordance is kept); Admin
  Center `#` tabs unchanged.
