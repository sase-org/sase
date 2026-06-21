---
create_time: 2026-06-21 08:13:25
status: done
prompt: sdd/prompts/202606/startup_stopwatch_escalation_colors.md
---
# Plan: Escalating Color Ramp for the `sase ace` Startup Stopwatch

## Problem / Context

When the `sase ace` TUI launches, the bottom-right **AXE status indicator** is temporarily replaced by a live
**"Starting" stopwatch** badge (e.g. `  ◴ starting 2.4s  `) that ticks every 0.1s until the first axe-status load
completes (~3.5s in the common case), then hands off to the real AXE status pill (`RUNNING` / `STOPPED` / …).

Today the stopwatch has only **two** color states:

- `0–10s`: amethyst purple `rgb(155,89,182)` ("starting normally")
- `≥10s`: raspberry magenta `rgb(214,51,132)` ("this is taking a while")

The user wants a finer-grained, more expressive **escalation ramp** that communicates "startup is dragging" with
increasing urgency, and to make it genuinely beautiful:

- **yellow after 3s**
- **orange after 5s**
- **red after 8s**
- **flashing red, emphasized after 13s**

The user explicitly asked me to lead the design and prioritize a beautiful result.

## Current Implementation (where the change lands)

All stopwatch rendering lives in two presentation-only Python files:

- `src/sase/ace/tui/widgets/_keybinding_status.py` — `KeybindingStatusMixin`. Owns the color/glyph constants, the
  per-tick handler (`_on_stopwatch_tick`), the render method (`_get_status_text`), and the repaint-coalescing signature
  (`_status_signature`). The current two-tier color choice is the single
  `if elapsed >= _STARTUP_STOPWATCH_SLOW_THRESHOLD_SECS` branch in `_get_status_text`.
- `src/sase/ace/tui/widgets/keybinding_footer.py` — `KeybindingFooter`. Owns widget state/init, the `on_mount` 0.1s
  `set_interval` tick, and re-exports the stopwatch constants (used by tests).

The badge is rendered as three Rich `Text` segments — rotating clock glyph (`◴◷◶◵`), the word `starting`, and the
elapsed counter — each styled `<fg> on <bg>`. The tick advances both `_startup_elapsed` and `_stopwatch_frame`; because
`round(elapsed, 1)` is part of the render signature, the badge already repaints on every 0.1s tick. A 30s safety timeout
tears the stopwatch down if startup hangs; a normal handoff ends it via `end_startup_stopwatch()`.

## Design

### The escalation ramp (heat-up model)

The badge stays **calm** during a healthy startup and only **heats up** the longer it drags — a heat/alarm gradient the
eye reads instantly:

| Elapsed | Tier         | Background                               | Foreground | Notes                                |
| ------- | ------------ | ---------------------------------------- | ---------- | ------------------------------------ |
| `0–3s`  | baseline     | amethyst `rgb(155,89,182)` (kept)        | white      | "starting normally" — the calm state |
| `3–5s`  | yellow       | amber `rgb(250,204,21)`                  | **black**  | mild "taking a beat"                 |
| `5–8s`  | orange       | orange `rgb(249,115,22)`                 | **black**  | concern                              |
| `8–13s` | red          | red `rgb(220,38,38)`                     | white      | alarm                                |
| `≥13s`  | flashing red | pulses `rgb(255,40,40)` ↔ `rgb(120,0,0)` | white      | flashing + emphasized — "stuck"      |

Foreground color is chosen per tier for **WCAG-readable contrast**: black ink on the light amber/orange backgrounds
(matching the proven AXE `STARTING`/`STOPPING` pills), white on the dark amethyst/red backgrounds (matching `STOPPED`).
The glyph and counter stay bold; the `starting` label stays regular weight — preserving today's subtle emphasis
hierarchy.

### Key design decision: keep amethyst purple for the first 3 seconds

The user specified colors for 3s/5s/8s/13s but not for the `0–3s` window. I am **keeping the existing amethyst purple
baseline** there, deliberately:

- In the common case the whole stopwatch lifetime is < 3.5s, so most users only ever see the calm amethyst (maybe a
  brief flash of yellow at the tail). Startup should not _look_ like a warning when nothing is wrong.
- It preserves the one property the prior design (`sdd/tales/202604/stopwatch_color_refresh.md`) cared about most: in
  the normal fast-startup path the badge color is **distinct from every AXE status pill**, so the stopwatch→pill handoff
  is still an unmistakable phase change.

### Deliberate trade-off: warm tiers now overlap the AXE pill hues

The prior design chose purple/magenta _specifically_ to avoid yellow/orange/red, because those are the AXE pill colors
(`STARTING`=yellow, `STOPPING`=orange, `STOPPED`=red). The user's new request intentionally reverses that for the
escalation tiers. This is an acceptable, well-scoped trade-off:

- The overlap only appears in the **abnormal** slow-startup case (≥3s) — exactly when an escalating warning is
  _desirable_. The normal case stays amethyst (no overlap).
- Even when a warm stopwatch hands off to a same-hue pill (e.g. red stopwatch ≥8s → red `STOPPED`), the badge **text**
  still changes (`starting 9.1s` → `STOPPED`), so the handoff remains legible, and a red→red transition is _semantically
  coherent_ (both say "something's off").
- The existing regression test that forbade any pill-colored stopwatch background
  (`test_stopwatch_colors_distinct_from_axe_pills`) is **reframed**, not deleted: it will now guard that the
  **baseline** (amethyst) stays distinct from all pills — the property that still matters.

### "Flashing red, emphasized" (≥13s) — self-driven pulse, not terminal blink

There is no existing reliance on the terminal `blink` SGR attribute anywhere in the TUI, and terminal support for it is
inconsistent. Instead the flash is **self-driven** off the stopwatch's existing 0.1s tick / `_stopwatch_frame` counter,
which guarantees a deterministic, terminal-agnostic, tasteful flash:

- The background alternates between a bright alarm red `rgb(255,40,40)` and a deep red `rgb(120,0,0)` every ~0.5s (5
  ticks per half-cycle → ~1 Hz), reading clearly as a pulsing red beacon while the white bold text stays readable in
  _both_ phases (no strobe, no unreadable frame).
- **Emphasized**: in this tier the `starting` label is also rendered bold (the whole badge gains weight), distinguishing
  it from the steady red `8–13s` tier. The clock glyph keeps rotating, so the badge still reads as a live stopwatch.
- The flash phase is folded into the render signature (via the computed background), so a phase flip always triggers a
  repaint without adding any new timer or I/O.

## Implementation Overview

All edits are presentation-only and localized to the two widget files plus their unit tests.

### `src/sase/ace/tui/widgets/_keybinding_status.py`

1. **Constants.** Remove `_STARTUP_STOPWATCH_SLOW_THRESHOLD_SECS`, `_STOPWATCH_BG_SLOW`, and the single `_STOPWATCH_FG`.
   Keep `_STARTUP_STOPWATCH_TIMEOUT_SECS` (30s) and `_STOPWATCH_GLYPH_FRAMES`. Keep `_STOPWATCH_BG_NORMAL` (amethyst
   baseline). Add the tier thresholds (`_STOPWATCH_TIER_YELLOW_SECS = 3.0`, `…_ORANGE_SECS = 5.0`, `…_RED_SECS = 8.0`,
   `…_FLASH_SECS = 13.0`), the tier backgrounds (`_STOPWATCH_BG_YELLOW`, `_BG_ORANGE`, `_BG_RED`, `_BG_FLASH_ON`,
   `_BG_FLASH_OFF`), the two foregrounds (`_STOPWATCH_FG_LIGHT = "white"`, `_STOPWATCH_FG_DARK = "black"`), and a
   flash-cadence constant (`_STOPWATCH_FLASH_PERIOD_TICKS = 5`).

2. **Pure palette helper.** Add a small pure function `_stopwatch_palette(elapsed, frame) -> (bg, fg, emphasized)` that
   selects the tier by elapsed (highest threshold wins) and, for the flash tier, derives the pulsing background from
   `frame // _STOPWATCH_FLASH_PERIOD_TICKS`. Pure and trivially unit-testable.

3. **Render.** Rewrite the stopwatch branch of `_get_status_text()` to call the helper and style the three segments:
   glyph `bold {fg} on {bg}`, label `{fg} on {bg}` (or `bold …` when emphasized), counter `bold {fg} on {bg}`. Padding,
   glyph rotation, one-decimal formatting, and bgcmd-badge appending are unchanged.

4. **Signature.** Include the computed background in the startup branch of `_status_signature()` so tier changes and
   flash-phase flips always repaint. (Behavior-preserving: elapsed already changes every tick; this just makes the flash
   contract explicit.)

### `src/sase/ace/tui/widgets/keybinding_footer.py`

5. Update the constant re-export block to match the renamed/added constants so unit tests can import them from
   `keybinding_footer`. No logic change (`on_mount` tick, state init, lifecycle untouched).

## Tests

Rewrite/extend `tests/ace/tui/widgets/test_keybinding_footer_stopwatch.py` (unit-level, matching the existing test style
— no app mount required):

- **Keep & adapt:** default-state-shows-stopwatch, one-decimal formatting, end→real-status, idempotent end,
  bgcmd-badges-co-render, frame-rotation-advances (update glyph/constant imports).
- **New tier boundaries:** at representative elapsed values (e.g. 1s/3s/4.9s/5s/8s/13s) assert the rendered spans carry
  the expected background (amethyst / amber / orange / red / flash-red), including just-below vs. just-at each
  threshold.
- **New flash behavior:** with `elapsed = 14s`, stepping `_stopwatch_frame` across a full cycle produces _both_
  `_BG_FLASH_ON` and `_BG_FLASH_OFF` backgrounds (the pulse actually alternates), and the `starting` label span is bold
  (emphasis) in this tier only.
- **Reframed distinctness guard:** assert the **baseline** background is not equal to any AXE pill background
  (preserving normal-case handoff legibility); drop the old assertion that _all_ stopwatch backgrounds avoid pill hues
  (now intentionally false for the warm tiers).

Manual smoke test: `sase ace` with axe stopped — watch the badge tick amethyst, and (forcing a slow first load, e.g. a
temporary sleep in the axe-status loader) confirm the yellow→orange→red→pulsing-red escalation and that the 30s safety
timeout still ends it.

## Boundary & Convention Checks (all clear)

- **Rust core boundary** (`memory/rust_core_backend_boundary.md`): this is presentation-only Textual rendering — colors,
  thresholds, glyph styling. No shared backend behavior; **no `sase-core` change**.
- **TUI performance** (`memory/tui_perf.md`): no new timers, threads, or I/O; the existing 0.1s tick and signature
  short-circuit are reused. The flash adds only arithmetic in a pure helper. No event-loop work, no regression.
- **Visual snapshots**: the PNG snapshot harness always ends the startup stopwatch before capture
  (`tests/ace/tui/visual/_ace_png_snapshot_helpers.py` → `_maybe_end_startup_stopwatch()`), so the stopwatch never
  appears in any golden — **no goldens need regenerating**, and the `footer_leader_overflow_*` snapshots are unaffected.
- **Help popup / CLI / keymaps**: no option, keybinding, or CLI surface changes, so the `?` help modal, `cli_rules`, and
  `default_config.yml` are untouched.
- **Lint**: ruff ignores `F401`, so the re-export imports remain fine.

## Rollout

Pure TUI polish — single commit, no migration, no config, no CLI change. Run `just install` then `just check` before
finishing.

## Deliberately Out of Scope

- Changing the `0–3s` baseline color or the 30s safety timeout.
- User-configurable stopwatch thresholds/palette.
- Adding a dedicated PNG snapshot for the stopwatch tiers (the harness ends the stopwatch before capture; deterministic
  visual coverage would require new scaffolding — can be a follow-up if the unit-level color assertions prove
  insufficient).
- Re-auditing the broader gold/yellow color overload elsewhere in the TUI.
