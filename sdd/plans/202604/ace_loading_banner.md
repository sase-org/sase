---
create_time: 2026-04-23 15:53:21
status: wip
prompt: sdd/prompts/202604/ace_loading_banner.md
---

# Bold, Beautiful Startup Loading Banner for `sase ace` TUI

## Problem

The `sase ace` TUI opens in ~300ms but the first ~3 seconds show dim spinners (`…` glyphs + small braille
`LoadingIndicator`s on panels) while agents and axe status finish loading asynchronously. This works, but the signal is
subtle — a new or infrequent user may still read the screen as "broken" or "empty" before the content arrives.

We want an additional, **visually prominent**, **bold** loading indicator that:

- Unambiguously tells the user: _the TUI is still loading, hold on_.
- Looks **beautiful** — cohesive with the existing Textual theme, not garish, not childish.
- Disappears as soon as both the agents load and the axe status load complete (i.e. both `_agents_first_load_done` and
  `_axe_first_load_done` are `True`).
- Does **not** re-appear on auto-refresh, tab switches, or any subsequent load cycle.
- Does **not** appear at all on a warm cache where both flags are already `True` by the time the banner would mount.
- Does **not** reflow/shift content when it disappears.

## Design Options Considered

| Option                                                                                       | Pros                                                                                   | Cons                                                                                                     | Verdict             |
| -------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- | ------------------- |
| **A. Top full-width banner row** — insert a new row between `#top-bar` and `#main-container` | Simple to implement (normal compose child)                                             | Reflows main content by 1–3 rows when it disappears → jarring                                            | ✗                   |
| **B. Centered floating overlay card** (own layer, docked top-center)                         | Prominent, unambiguous, no reflow, looks like a modern TUI status toast (k9s, lazygit) | Requires `layers:` in TCSS and one extra widget                                                          | **✓ RECOMMENDED**   |
| **C. Extra indicator inside `#top-bar`**                                                     | Zero layout risk, already 1-row tall                                                   | Constrained to 1 line next to `TaskIndicator` / `NotificationIndicator` — cannot be "bold and prominent" | ✗ (not bold enough) |
| **D. Toast via Textual `notify()`**                                                          | Built-in                                                                               | Auto-dismisses on a timer, not on a state condition; wrong lifecycle                                     | ✗                   |
| **E. Inline inside each tab's info panel**                                                   | Already has `set_loading()`                                                            | Tab-scoped; user on CLs tab wouldn't see it; not "bold"                                                  | ✗                   |

**Choosing B** — a compact centered floating card, docked near the top of the screen on an overlay layer. It sits on top
of whatever tab is active, is guaranteed visible on first paint regardless of tab, disappears in place (no reflow), and
carries enough pixels for a genuinely bold typography treatment. The ~10 LoC of TCSS overhead is a fair trade for the
visual clarity.

## Visual Design

One centered card, 3 rows tall, auto-width (sized to its content), docked to the top of the screen just below the
`Header()` bar, on its own layer above the main content.

```
                ╭──────────────────────────────────╮
                │  ⠋  Starting sase ace…           │
                ╰──────────────────────────────────╯
```

Content is a `Horizontal` with two children:

1. **`LoadingIndicator`** — the built-in Textual braille-dot spinner (`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`). Uses theme color automatically.
   Width 3, height 1, no margin.
2. **`Static` label** — bold Rich text: **`Starting sase ace…`** in `$primary` color. Optionally a dim italic subtitle
   on a second line if we want more info (deferred — start with a single line; revisit if research shows we need it).

Typography:

- `text-style: bold`
- `color: $primary` _(matches the tab accent palette — already used across the app)_
- Border: `round $primary` — rounded corners, same theme color, looks like a polished card.
- Background: `$panel` — Textual's neutral card background, slightly darker than the main surface. Provides contrast
  against whatever view sits underneath so the banner reads as a distinct overlay rather than a layout element.
- Padding: `0 2` (0 vertical, 2 horizontal) — lets the border breathe without stealing rows.

**Why `$primary` instead of `$warning` / `$accent`:**

- `$warning` (amber/yellow) says "something needs your attention" — wrong tone for "we're still loading, everything's
  fine".
- `$accent` is reserved for selection highlight — reusing it for a banner would mute selection semantics elsewhere.
- `$primary` is already the color of the active tab underline and the panel spinners — so the banner _harmonizes_ with
  the existing loading vocabulary instead of introducing a new signal.

**Animation:** Inherited for free from `LoadingIndicator` (braille-dot pulse). No custom keyframes, no shimmer, no
opacity fade. One animation on screen, not two.

**Sizing:** `width: auto` and `height: 3`. The card grows horizontally to fit the text; the TCSS `align: center top` on
its parent layer keeps it centered regardless of terminal width.

## State Machine

Two inputs: `_agents_first_load_done` and `_axe_first_load_done`. One derived property:

```python
@property
def _is_initial_load_pending(self) -> bool:
    return not (self._agents_first_load_done and self._axe_first_load_done)
```

Lifecycle:

| Moment                                     | Both flags True?          | Banner state                                     |
| ------------------------------------------ | ------------------------- | ------------------------------------------------ |
| `on_mount` (cold cache)                    | No                        | **shown**                                        |
| `on_mount` (warm cache, both already True) | Yes                       | **never shown** (mounted hidden, stays hidden)   |
| agents finish loading first                | No (axe still pending)    | still **shown**                                  |
| axe finishes loading first                 | No (agents still pending) | still **shown**                                  |
| second of the two finishes                 | Yes                       | **hidden** (smooth graceful removal — see below) |
| any auto-refresh after this point          | Yes (flags never reset)   | stays **hidden** forever                         |
| tab switch                                 | unchanged                 | unchanged                                        |

"Graceful removal": set the `-hidden` CSS class (a `display: none` toggle). The card disappears in place — no reflow
because it's on its own layer over the main content. Optionally add a 200ms opacity transition in TCSS if Textual's
`transition` property is honored for this (low priority — start without, add only if it looks abrupt in manual test).

**Idempotency guard:** The hide logic runs from both `_apply_loaded_agents` and `_apply_axe_status_data`. Whichever
finishes second hides the banner. A `.has_class("-hidden")` check avoids double-toggling.

## File-by-file Changes

### 1. New widget — `src/sase/ace/tui/widgets/startup_loading_banner.py`

Small self-contained widget:

```python
class StartupLoadingBanner(Horizontal):
    """Bold, centered, floating 'starting up' banner shown during initial load."""
    DEFAULT_CSS = ""  # all styling in styles.tcss

    def compose(self) -> ComposeResult:
        yield LoadingIndicator(id="startup-loading-banner-spinner")
        yield Static("Starting sase ace…", id="startup-loading-banner-label")

    def hide(self) -> None:
        if not self.has_class("-hidden"):
            self.add_class("-hidden")
```

Why its own file: keeps `app.py` compose tree readable, mirrors the existing pattern of one widget per file under
`widgets/`.

### 2. `src/sase/ace/tui/app.py`

- **Import** the new widget at the top.
- **`compose()`** — yield `StartupLoadingBanner(id="startup-loading-banner")` once, between the top-bar and
  `#main-container`. The `layer:` TCSS rule lifts it out of the normal flow so sibling order doesn't affect layout —
  placing it near the top of compose is just for readability.
- **`on_mount`** / `_apply_startup_loading_state` — if `_is_initial_load_pending` is `False` at mount time (warm cache),
  immediately add the `-hidden` class to the banner so it never paints. Otherwise it remains visible by default.
- **New helper `_maybe_hide_startup_banner()`** — called from both apply-callbacks. Checks `_is_initial_load_pending`;
  if `False`, looks up `#startup-loading-banner` and calls `.hide()`.

### 3. `src/sase/ace/tui/actions/agents/_loading.py`

- Inside `_apply_loaded_agents`, in the existing `if not self._agents_first_load_done:` block (right after flipping the
  flag and clearing panel `.loading`), add one line: `self._maybe_hide_startup_banner()`.

### 4. `src/sase/ace/tui/actions/axe_display.py`

- Inside `_apply_axe_status_data`, in the existing `if not self._axe_first_load_done:` block, add one line:
  `self._maybe_hide_startup_banner()`.

### 5. `src/sase/ace/tui/styles.tcss`

Add the overlay layer and banner styling. Approximate TCSS (exact rules tuned during implementation):

```tcss
Screen {
    layers: base overlay;
}

#startup-loading-banner {
    layer: overlay;
    dock: top;
    align-horizontal: center;
    offset: 0 2;            /* sit just below the 1-row Header */
    width: auto;
    height: 3;
    padding: 0 2;
    background: $panel;
    border: round $primary;
    color: $primary;
    text-style: bold;
}

#startup-loading-banner-spinner {
    width: 3;
    height: 1;
    margin-right: 1;
}

#startup-loading-banner-label {
    height: 1;
    color: $primary;
    text-style: bold;
}

#startup-loading-banner.-hidden {
    display: none;
}
```

Notes:

- `layers: base overlay` on `Screen` is the only global change — everything else already sits on the default base layer,
  so adding `overlay` is additive.
- `dock: top` + `align-horizontal: center` is the standard Textual idiom for a top-centered floating element.
- `offset: 0 2` assumes the built-in `Header()` is 1 row tall + 1 row of breathing space. If `Header()` is taller in
  some themes, adjust at implementation time.
- **Do not** globally style `LoadingIndicator` — only scope the spinner rules by id so the existing per-panel spinners
  (agent list, axe dashboard) are unchanged.

## Test Strategy

### Automated

Add `tests/ace/tui/test_startup_loading_banner.py` (mirrors the pattern in `test_startup_loading_indicators.py`):

1. `test_banner_mounts_visible_when_both_flags_false` — construct `AceApp`, assert that after
   `_apply_startup_loading_state` the banner does **not** have the `-hidden` class.
2. `test_banner_mounts_hidden_when_both_flags_true` — force both flags `True` before `on_mount`; assert banner has
   `-hidden` class immediately (warm-cache case).
3. `test_banner_hides_when_axe_finishes_second` — with only `_agents_first_load_done=True`, call
   `_maybe_hide_startup_banner`; banner still visible. Then flip `_axe_first_load_done=True` and call again; banner
   hidden.
4. `test_banner_hides_when_agents_finish_second` — mirror image of #3.
5. `test_banner_hide_is_idempotent` — call `.hide()` twice, no exception, class set exactly once.
6. `test_banner_does_not_reappear_after_refresh` — simulate an auto-refresh by directly re-invoking
   `_apply_loaded_agents` / `_apply_axe_status_data`; the flag-gated block never runs, banner stays hidden.

### Manual

1. Cold cache: `rm -rf ~/.sase/home/tmp/sase/_json_cache && sase ace`
   - First paint: bold centered card visible, spinner animating, text reads "Starting sase ace…".
   - ~3s later: card vanishes in place, no reflow, existing panels fill in.
2. Warm cache: `sase ace` again immediately.
   - Banner should be absent from first paint. (Not a one-frame flash — ideally not visible at all.)
3. Tab-switch during load: start on CLs tab, switch to axe, back. Banner stays overlayed consistently, no flicker.
4. Post-load user actions (dismiss, kill, mark) work identically — banner never re-appears.
5. Resize terminal during load: banner re-centers.
6. `sase ace --profile`: banner is visible in the profile screenshot/video.

### `just check`

Must pass: ruff, mypy, pytest.

## Don't Do

- **Don't insert the banner as a normal flow row above `#main-container`.** That causes reflow when it disappears.
  Layer-based overlay is the right primitive here.
- **Don't use `Textual.notify()` / toast system.** Toasts auto-dismiss on a timer; we need state-driven dismissal.
- **Don't style `LoadingIndicator` globally.** Only scope by `#startup-loading-banner-spinner` id so existing per-panel
  spinners keep their defaults.
- **Don't introduce a new color.** Reuse `$primary` (already the tab-accent color) to keep the visual vocabulary
  coherent.
- **Don't animate opacity or add a custom shimmer.** The built-in `LoadingIndicator` is already animated; doubling up is
  noise.
- **Don't reset the flags on tab-switch or refresh.** The banner is tied to flags that are one-way-only by design;
  re-showing the banner on every auto-refresh would be infuriating.
- **Don't tie the banner to a _third_ boolean.** The existing two flags are sufficient — computing
  `_is_initial_load_pending = not (agents_done and axe_done)` is enough.
- **Don't touch `ChangeSpec` loading.** ChangeSpecs load synchronously before first paint; they have no part in this
  banner's lifecycle.
- **Don't use a multi-line message by default.** Start with one line ("Starting sase ace…"). Only add a dim italic
  subtitle if a manual run shows the single line reads as underwhelming.
