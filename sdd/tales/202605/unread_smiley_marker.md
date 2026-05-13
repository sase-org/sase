---
create_time: 2026-05-13 13:27:27
status: done
prompt: sdd/prompts/202605/unread_smiley_marker.md
---
# Plan: Replace the unread-agent mailbox marker with a yellow smiley face

## Context

The `sase ace` Agents tab renders a right-edge **runtime suffix marker** on each agent row, occupying a single emoji
slot just before the elapsed-time / timestamp text. The marker has three mutually exclusive variants — running,
**unread-completed**, and user-paused — defined as string + style constants in
`src/sase/ace/tui/widgets/_agent_list_render_layout.py` and consumed by `build_runtime_suffix`.

Today the unread-completed marker is **📬** (mailbox with raised flag), styled `#5FD7FF` (cool sky-blue). It was chosen
over an earlier 🎉 because the mailbox metaphor reads as "you have unseen output". The user now wants to swap that
mailbox for a **yellow smiley face**.

## Goal

Replace the unread-completed marker `📬` with a yellow smiley face emoji, keeping all surrounding rendering behavior
unchanged.

## Files involved

Marker definition (single source of truth):

- `src/sase/ace/tui/widgets/_agent_list_render_layout.py:44` — `_RUNTIME_UNREAD_COMPLETED_MARKER = "📬 "`
- `src/sase/ace/tui/widgets/_agent_list_render_layout.py:45` — `_RUNTIME_UNREAD_COMPLETED_MARKER_STYLE = "#5FD7FF"`
- The marker is referenced in four spots inside `build_runtime_suffix` (lines 87–122). No logic changes are needed —
  only the constants.

Tests that assert on the literal emoji:

- `tests/ace/tui/widgets/test_agent_list_runtime_rendering.py` — 5 assertions on `📬` (lines 106, 121, 143, 203, 355,
  364, 376).
- `tests/ace/tui/widgets/test_agent_render_cache.py` — 3 assertions (lines 335, 450, 452).

Docs:

- `docs/ace.md:527` — prose mentions "`📬` marker in the same suffix slot".

Visual snapshots:

- `tests/ace/tui/visual/snapshots/png/` — any PNG that bakes an unread-completed row needs regeneration via
  `just test-visual --sase-update-visual-snapshots`. The change is purely a glyph swap, so each diff should differ only
  in the marker pixels.

Out of scope (intentionally untouched):

- The other suffix markers (`🏃‍♂️` running, `✋` user-paused).
- BY_STATUS bucket banner glyphs (`▲ ▶ ⏳ ✗ ✓`) in `src/sase/agent/status_buckets.py`.
- The mark / approve / hidden / bead context glyphs (`✓ ⚡ ◌ ◆`) in `_agent_list_styling.py`.
- Rust `sase-core` — these markers are pure Python presentation state.
- Historical SDD records under `sdd/tales/`, `sdd/prompts/`, `sdd/research/` that mention the old glyph. Tales describe
  past decisions; rewriting history makes them lie.

## Candidate emoji

"Yellow smiley face" maps to several glyphs. Ranked by fit for the unread-completed slot:

| Glyph | Reads as                | Pros                                                          | Cons                                                                         |
| ----- | ----------------------- | ------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| 🙂    | "slightly smiling face" | Single codepoint, minimal, calm — doesn't shout "celebration" | Subtle; small-font terminals may render the mouth as a near-flat dot         |
| 😀    | "grinning face"         | Strong, friendly read at small sizes                          | Slightly closer to the old 🎉 "yay done" celebratory tone we moved away from |
| 😊    | "smiling face w/ eyes"  | Warmest of the set; pleasant "good news waiting" feel         | Cheek-blush detail muddies at terminal sizes                                 |
| 😃    | "grinning w/ big eyes"  | Very legible, expressive                                      | Reads as excited / loud — similar concern as 😀                              |

**Recommendation:** **🙂** — calm, scannable, and the cleanest single-codepoint match for "yellow smiley face". Will
confirm with the user before editing in case they want the more expressive 😀 or 😊.

## Color (style) handling

The marker is appended with `style=_RUNTIME_UNREAD_COMPLETED_MARKER_STYLE`. Emoji glyphs render in their **intrinsic
colors** in modern terminals, so the foreground style largely affects only the trailing space, not the smiley itself.
Two options:

1. **Keep `#5FD7FF` (sky-blue).** Style cost is invisible (one space), and we avoid touching anything we don't need to.
   The smiley still renders yellow.
2. **Switch to a yellow like `#FFD75F`.** Semantically consistent ("yellow icon, yellow style") and lines up with the
   running marker's gold family — but that collision was originally _avoided_ to keep the three suffix variants in
   distinct color families. The collision is mostly theoretical here because the styled span is just a single space.

**Recommendation:** **option 1** — keep `#5FD7FF`. The visible glyph color comes from the emoji itself, and leaving the
style alone minimizes the diff and preserves the row-color family separation in case we ever extend the styled span
later.

## Implementation outline

1. Edit `src/sase/ace/tui/widgets/_agent_list_render_layout.py`:
   - Change `_RUNTIME_UNREAD_COMPLETED_MARKER` from `"📬 "` to `"🙂 "` (pending user confirmation of the exact glyph).
   - Leave `_RUNTIME_UNREAD_COMPLETED_MARKER_STYLE` unchanged (see color section above).
2. Update the literal `📬` assertions in:
   - `tests/ace/tui/widgets/test_agent_list_runtime_rendering.py`
   - `tests/ace/tui/widgets/test_agent_render_cache.py`
3. Update the prose reference in `docs/ace.md` (one sentence around line 527).
4. Regenerate visual snapshots via `just test-visual --sase-update-visual-snapshots`, then inspect each diff under
   `.pytest_cache/sase-visual/` to confirm only the marker pixels changed.
5. Run `just check` to validate lint + types + tests.

## Validation plan

- `just check` passes.
- Launch `sase ace` against a project with at least one unread completed agent and confirm the new smiley renders in the
  runtime-suffix slot for that row, with running 🏃‍♂️ and paused ✋ rows still rendering their own markers.
- Spot-check a row that is _both_ unread and ticking — `is_ticking=True` wins and the running marker should still take
  the slot (no smiley shown).

## Open question for the user

Confirm the recommended glyph (**🙂**) — or pick **😀**, **😊**, or **😃** from the candidate table — before I edit.
Also confirm whether to leave the style at `#5FD7FF` (recommended) or swap it to a yellow like `#FFD75F`.
