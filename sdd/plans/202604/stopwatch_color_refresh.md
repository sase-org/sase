---
create_time: 2026-04-24 15:05:44
status: done
prompt: sdd/prompts/202604/stopwatch_color_refresh.md
---

# Plan: Refresh Startup Stopwatch Colors & Polish

## Problem

The startup stopwatch in `sase ace`'s bottom-right corner currently uses colors that overlap with the AXE status
indicator that _replaces_ the stopwatch once startup completes. Because the two views share the same slot, a user
glancing at the corner during the flicker-free hand-off should see an unmistakable _color_ change — today the change is
nearly imperceptible.

Concretely, in `src/sase/ace/tui/widgets/keybinding_footer.py`:

| State            | Current bg                   | Overlap                                                                                             |
| ---------------- | ---------------------------- | --------------------------------------------------------------------------------------------------- |
| Stopwatch <10s   | gold `rgb(255,215,0)`        | nearly identical to STARTING yellow `rgb(255,255,0)` and to the `[✓D]` bgcmd-done badge (`#FFD700`) |
| Stopwatch ≥10s   | dark-orange `rgb(255,140,0)` | practically identical to STOPPING `rgb(255,165,0)`                                                  |
| STARTING (AXE)   | yellow `rgb(255,255,0)`      | —                                                                                                   |
| STOPPING (AXE)   | orange `rgb(255,165,0)`      | —                                                                                                   |
| RESTARTING (AXE) | cyan `rgb(0,191,255)`        | —                                                                                                   |
| RUNNING (AXE)    | green                        | —                                                                                                   |
| STOPPED (AXE)    | red                          | —                                                                                                   |

The overlap is a real usability bug: during the ~3.5s startup window the stopwatch is visually indistinguishable from
the STARTING pill, and after 10s it becomes indistinguishable from the STOPPING pill. The hand-off from stopwatch → AXE
status should be a clear "phase change" that the eye catches immediately.

In addition, the stopwatch's visual treatment is functional but minimal — the user has asked us to make it more
_beautiful_ while we're in the area.

## Design Goals

1. **Distinct** — the stopwatch's color palette must not collide with _any_ color used for the AXE status pills (yellow
   / orange / cyan / green / red).
2. **Coherent** — keep the padded-badge convention, bold face, one-decimal elapsed formatting, and the 10s-slow /
   30s-timeout lifecycle. Only cosmetic details change.
3. **Beautiful & alive** — the stopwatch is a _temporary_ UI moment; it can afford a touch more character than the
   permanent status pills. The goal is "delightful brief flash," not "shouty novelty."
4. **Accessible** — foreground/background contrast must remain WCAG-AA-ish readable; avoid pairings that hurt common
   forms of color-blindness (red/green or similar-lightness swaps).
5. **No behavioral regressions** — safety timeout, `_axe_first_load_done` hand-off, bgcmd badge co-display, and all
   existing tests' intent remain intact.

## Color Choice — Purple/Magenta Family

The AXE status cascade already owns the warm-and-green half of the color wheel (red, orange, yellow, green) plus a
cyan-blue for RESTARTING. That leaves **purple / magenta / pink** as the cleanest distinct region.

**Primary (normal, 0–10s):** `rgb(155,89,182)` — **amethyst purple**.

- Genuinely distinct from every AXE status color.
- Reads as _calm, active, positive_ — not alarming. A user seeing this during startup intuits "working" rather than
  "warning."
- Also distinct from the `[✓D]` bgcmd-done gold badge and the `[*R]` bgcmd teal-cyan badge — so the stopwatch and any
  coincident bgcmd badges each remain visually unambiguous.

**Slow (≥10s):** `rgb(214,51,132)` — **raspberry magenta**.

- Stays in the purple/pink family (preserves family identity of the stopwatch state) but shifts warmer/higher-energy —
  an intuitive "this is taking longer than usual" escalation, mirroring the original gold→orange intent.
- Still clearly distinct from AXE red (`red`, pure `#FF0000`): raspberry magenta is hue ≈334°, red is hue 0°. On ANSI
  24-bit terminals, they read as different colors; on 256-color fallback both are still obviously not the same family.
- Never co-exists with STOPPED red on screen (stopwatch is torn down the instant the real status flips in), so any
  residual red/magenta adjacency concern is moot in practice.

**Foreground:** `bold white` on both backgrounds. White-on-amethyst and white-on-raspberry both clear WCAG-AA for bold
text; black-on-amethyst is marginal. We sacrifice the minor downside (losing the "black ink on gold" aesthetic) for
consistent, clearly-readable text.

## Beauty Pass — What Else Changes

Three small touches, each doing one job:

### 1. Animated "stopwatch face" glyph

Replace the static `⏱` (emoji, variable terminal width, visually flat) with a **4-phase rotating clock-quadrant
spinner**:

```
◴  ◷  ◶  ◵   (then loop)
```

These are single-cell Unicode box-drawing/symbol glyphs (`U+25F4..25F7`) that render at a predictable monospace width in
every terminal we target. Each 0.1s tick advances the frame index by one — the eye sees a small clock-face rotating in
lockstep with the number updating, which makes the badge feel genuinely alive without resorting to gaudy animation.

_Why this over a Braille spinner `⠋⠙⠹⠸…`?_ The clock quadrants preserve the **stopwatch semantics** (still reads as a
clock), while a Braille spinner would read as a generic "loading" indicator. Given the widget _is_ a stopwatch, the
clock-rotation metaphor is strictly better.

### 2. Emphasis-pair inside the badge

Today the badge is one `text.append(...)` with a single style. Break it into three appends so the **elapsed number gets
its own emphasis**:

```
[ ◴ ] [ starting ] [ 2.4s ]
  glyph        label          counter
```

- Glyph: bold, slightly dim face (so the rotation reads as a subtle accent, not a distraction from the number).
- Label: regular (not dim — dim on a colored bg is hard to read).
- Counter: bold + background emphasis unchanged — the counter is what the user is actually watching.

Padding and whitespace stay identical to the other status pills (`" … "` on each side) so the corner footprint does not
change.

### 3. Optional: trim "starting" → "starting up"? → keep "starting"

Considered and rejected. "starting" is already the shortest word that reads as a verb in progress, matches the STARTING
AXE pill's vocabulary, and keeps badge width stable. Not touching it.

## Implementation Overview

All changes are localized to **`src/sase/ace/tui/widgets/keybinding_footer.py`**.

1. Add module-level constants near the existing stopwatch constants:

   ```python
   _STOPWATCH_GLYPH_FRAMES = ("◴", "◷", "◶", "◵")
   _STOPWATCH_BG_NORMAL = "rgb(155,89,182)"   # amethyst
   _STOPWATCH_BG_SLOW   = "rgb(214,51,132)"   # raspberry magenta
   _STOPWATCH_FG        = "bold white"
   ```

2. Add a `_stopwatch_frame: int = 0` field on the widget.

3. In `_on_stopwatch_tick`, increment `self._stopwatch_frame` alongside the existing elapsed-recompute. Modulo into the
   frames list at render time.

4. Rewrite the stopwatch branch of `_get_status_text()` to emit the three- part emphasis badge using the new color
   constants and the animated frame.

5. No other logic changes. The `end_startup_stopwatch()` path, safety timeout, `_axe_first_load_done` hand-off, and
   bgcmd badge appending all stay byte-identical.

### What does NOT change

- Public API of `KeybindingFooter` (no signature changes).
- `_apply_axe_status_data` in `src/sase/ace/tui/actions/axe_display/_loaders.py`.
- `AceApp.on_mount` and all startup phases.
- All AXE status pill colors (yellow/orange/cyan/green/red) and text.
- bgcmd badge colors and format.

### Edge cases

- **Rapid end (sub-tick):** stopwatch never paints; hand-off is instant. Same as today. Frame counter starting at 0 is
  fine either way.
- **Frame rollover:** `self._stopwatch_frame % 4` is cheap and correct even if the counter runs into large integers
  during the 30s window (it won't).
- **Terminals without 24-bit color:** Textual gracefully quantizes the `rgb(…)` values to the nearest 256-color index.
  Amethyst → ANSI 141 / 135; raspberry → ANSI 169. Both still read as purple/pink and are visually distinct from any AXE
  status pill in 256-color mode.
- **Colorblind users:** deuteranopia and protanopia both shift red and green toward yellow-brown, but purple/magenta
  remain recognizably blue/pink in both simulations — so the stopwatch stays distinct from red (STOPPED) and green
  (RUNNING) under common color-blindness types. (Tritanopia is the harder case — raspberry becomes red-ish — but STOPPED
  red is never co- displayed with the stopwatch, so practical confusion risk is nil.)

## Test Plan

Update `tests/ace/tui/widgets/test_keybinding_footer_stopwatch.py`:

1. **Default state shows stopwatch badge with new glyph:** assertion replaced — instead of `"⏱"` check for any of
   `_STOPWATCH_GLYPH_FRAMES` in `text.plain`, and still require `"starting"` in the text.
2. **Elapsed formatting** (unchanged intent): `2.4s`, `12.8s`, `0.1s`.
3. **Color threshold:**
   - `_startup_elapsed = 1.0` → spans contain `rgb(155,89,182)` (amethyst).
   - `_startup_elapsed = 15.0` → spans contain `rgb(214,51,132)` (raspberry).
4. **End transitions to real status** (unchanged intent): after `end_startup_stopwatch()`, no frame glyphs remain;
   STOPPED/RUNNING pills render correctly.
5. **Idempotence of end()** (unchanged).
6. **bgcmd badges co-render** (unchanged intent, updated glyph check).
7. **New: frame rotation advances per tick:** after manually calling `_on_stopwatch_tick()` four times,
   `self._stopwatch_frame` has advanced by at least 4 and `_stopwatch_frame % 4` cycles through all four frames. (Cover
   the distinctive animation contract so future refactors don't silently freeze the spinner.)
8. **Distinctness regression guard:** a unit test asserts that the stopwatch background colors (normal and slow) are
   _not_ any of the AXE pill backgrounds — so a future "let's use yellow again" change cannot silently reintroduce the
   overlap this plan is fixing.

Also update the one reference in `tests/test_keybinding_footer_status.py` if it asserts on the old gold/orange
backgrounds (grep suggests it currently only asserts on the AXE pill backgrounds, not the stopwatch — verify during
implementation).

Manual smoke test:

- `sase ace` with axe stopped → watch the purple stopwatch tick, see the clock quadrants rotate, confirm the hand-off to
  the red STOPPED pill is now an obvious _color change_ (purple → red) rather than a near-identical swap.
- `sase ace` with axe running → flash purple → green RUNNING. Obvious.
- Force slow startup → confirm the shift to raspberry at 10s and the safety timeout at 30s still works.

## Rollout

Pure TUI polish. Single commit. No migration, no config, no CLI change.

## Deliberately Out of Scope

- Broader audit of color overlaps elsewhere in the TUI (gold is heavily overloaded across the codebase — see `WIP`,
  `WAITING`, pinned agents, bgcmd done, etc.). That's a bigger conversation; this plan only addresses the
  stopwatch/AXE-status overlap in the one slot where they literally share pixels.
- User-configurable stopwatch theme. Can be added later.
- Animated elapsed digits, pulse effects, gradient fills — the 4-frame rotation is the right amount of motion for a
  badge that's on-screen for ≤3.5s most of the time.
