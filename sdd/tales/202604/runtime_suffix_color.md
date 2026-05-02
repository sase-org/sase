---
create_time: 2026-04-25 21:08:23
status: done
---
# Plan: Improve visibility of the runtime suffix on the Agents tab

## Goal

The right-aligned date/time + elapsed suffix introduced in `agents_tab_runtime_timestamp.md` is rendering nearly
invisible on the user's terminal. Restyle it so the answer to "how long?" / "when did it finish?" can actually be read
at a glance, while still feeling subordinate to the agent's name, status, and badges.

## Why the current styling reads as too faint

Today the suffix uses (in `src/sase/ace/tui/widgets/_agent_list_rendering.py`):

```python
_RUNTIME_TS_STYLE      = "dim #808080"
_RUNTIME_ELAPSED_STYLE = "dim"
```

Two compounding problems:

1. The `dim` Rich attribute is rendered by most terminals as ≈50% alpha on top of whatever color is provided. Combined
   with `#808080` (already a 50% grey), the timestamp half ends up at roughly `#404040` on a dark background — well
   below the legibility floor for small monospace glyphs.
2. The elapsed half has no color at all, so it inherits the foreground color _and_ gets the `dim` attribute. On a
   typical dark theme the result is a muddy washed-out grey that's hard to spot when scanning the right edge.

The rest of the agent-list palette (statuses in `#FFD700`/`#5FD75F`/`#FF5F5F`, name in `#00D7AF`, tag in `#5FAFFF`,
etc.) is fully saturated and bright. The contrast between primary content and the suffix is therefore much wider than
intended — the suffix doesn't read as "secondary metadata", it reads as "barely there".

## Design constraints

- Stay subordinate to the agent name and status — never use a saturated primary color (gold, green, red, pink, amber,
  amethyst, teal) that would let the suffix compete with the status word.
- Be readable on _both_ dark and light terminal backgrounds. That rules out pure greys near `#808080` (invisible on
  light themes when also `dim`) and near-white shades (invisible on light themes regardless).
- Harmonize with the existing palette. `dim #AFAFAF` is already used for the name-root banner rule — proven
  legible-but-secondary in this widget.
- Stay visually distinct as "metadata": same chrome on every row, no per-row variation.

## Recommended palette (two-tone)

Replace the existing two constants with:

```python
# Timestamp half: muted lavender-steel.  No `dim` attribute so the color
# carries on its own; chosen to harmonize with WAITING amethyst (#AF87FF)
# and project-banner sky-blue (#5FAFFF) while staying clearly less
# saturated, so the timestamp reads as a "metadata column" rather than a
# status word.
_RUNTIME_TS_STYLE = "#8787AF"

# Elapsed half: light neutral grey, bold to give the headline number
# ("how long?") a little more weight than the timestamp without using
# a saturated color.  Same hex Rich considers "ANSI bright black + a
# nudge" — readable on dark and light themes alike.
_RUNTIME_ELAPSED_STYLE = "bold #BCBCBC"
```

Bullet separator (`" · "`) keeps the timestamp style so `"20:17:03 ·"` reads as a single unit, with the elapsed value
visually breaking off as the answer.

### Why these specific values

- `#8787AF` — Sits between the `#5F87AF` already used for embedded-workflow pre-prompt arrows and the `#AF87FF` of
  WAITING. Neither is in the suffix's visual neighborhood (banners are full-row; WAITING text is on the left), so there
  is no risk of confusion. At HSL ≈(240°, 22%, 61%) it's saturated enough to be a "color" on dark backgrounds and dark
  enough to be readable on light ones.
- `bold #BCBCBC` — Light neutral, no hue, so it never clashes with whatever status color sits on the same row. Bold
  gives the elapsed digits ~10% extra stroke width on most terminal fonts, which is exactly what the original `dim`
  attribute was stripping. Net effect: readable but no chroma to compete with the status word.

### Why drop the `dim` attribute entirely

`dim` was the root cause of the legibility problem. Dropping it and instead choosing colors that are inherently muted
gives us:

- Predictable rendering across terminals (dim's actual appearance varies wildly between iTerm2, kitty, alacritty, the
  JetBrains terminal, tmux, etc.).
- The same "secondary" feel via _color choice_ rather than _alpha_, so the suffix degrades gracefully on monochrome /
  non-truecolor terminals (where Rich falls back to the nearest 256-color, still readable).

### Attempt-row duration

`_build_attempt_runtime_suffix` uses `_RUNTIME_ELAPSED_STYLE` as well, so attempt rows automatically pick up the new
bolder grey. That's correct: it's the same "headline duration" semantic.

The pre-existing `dim #FF8700` styling on the attempt-row left content (`Attempt N · 14:30:45 · status`) is unchanged —
it lives in `format_attempt_option`'s left text, not the suffix. The new bolder grey on the right end provides a nice
visual anchor without overlapping the orange.

## Considered and rejected alternatives

- **Mono-tone (both halves the same color)**: simpler but loses the "timestamp ≠ duration" distinction. The whole point
  of two halves is that the user's eye should be able to grab either piece quickly.
- **Saturated accent (e.g. cyan `#00D7D7`)**: too loud — would compete with status colors and pull the eye to the right
  side of every row.
- **Just remove `dim` and keep `#808080` / default fg**: fixes legibility but the default fg + `#808080` reads as
  "broken styling" rather than "metadata column". The suffix should look intentional.
- **Italic instead of bold for elapsed**: italic monospace renders as a slight slant on most terminal fonts and barely
  changes weight, so it doesn't actually buy us legibility.

## Files touched

- `src/sase/ace/tui/widgets/_agent_list_rendering.py` — only the two style constants change (and their accompanying
  comments). No structural change.

That's the entire change surface. The Text-construction code already pulls from these constants, so no other rendering
call sites need editing.

## Test plan

`tests/ace/tui/widgets/test_agent_list_runtime.py` asserts on `suffix.plain` (the raw character sequence) and on row
width — never on styles. **Verified**: every assertion in that file uses `.plain` or `len(...)`. The recolor is
therefore covered by the existing tests; they should continue to pass without modification.

`tests/ace/tui/widgets/test_agent_list_attempts.py` similarly only inspects `option.prompt.plain` for substring matches.
Unaffected.

No new tests are warranted — this is a pure visual tweak with no new behavior. Verifying the change visually in
`sase ace` is sufficient.

Run after the change:

```bash
just check
```

…to confirm formatting + type checks pass.

## Risks & mitigations

- **Color blindness / unusual themes**: `#8787AF` and `#BCBCBC` are both picked from the cool-neutral end of the palette
  and rely on _value_ (not hue) for legibility — so users with red-green color blindness, or on a blue-heavy theme like
  Solarized Dark, still see the contrast against the background. Mitigation: if any user reports unreadability we can
  fall back to a single `bold #BCBCBC` mono-tone variant trivially.
- **Light-theme readability**: `#BCBCBC` on a white background is the worst case. It's ~30% darker than the background —
  readable but low-contrast. Acceptable given the suffix is intentionally secondary; users on light themes who find it
  too faint can be addressed by a future follow-up that detects theme polarity (out of scope here).

## Non-goals

- No change to attempt-row left-side coloring (`Attempt N · ...` stays `dim #FF8700`).
- No change to banner styles, status colors, or any other agent-list palette.
- No new config option to choose colors — we keep the palette opinionated.
- No change to the `compute_row_runtime` semantics or the alignment math.
