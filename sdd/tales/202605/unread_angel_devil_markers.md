---
create_time: 2026-05-13 15:09:29
status: done
prompt: sdd/prompts/202605/unread_angel_devil_markers.md
---
# Plan: Angel / devil markers for unread agent rows

## Context

The `sase ace` Agents tab puts a single-emoji **runtime suffix marker** on each row, just before the elapsed-time /
timestamp text. There are three mutually exclusive variants today: running (`🏃‍♂️`), unread-completed (`🙂`), and
user-paused (`✋`). These are defined as string + style constants in
`src/sase/ace/tui/widgets/_agent_list_render_layout.py` and consumed by `build_runtime_suffix`.

The current unread-completed marker is **🙂** (set at line 44), styled `#5FD7FF`. It is applied uniformly to any
"unread + not ticking" row, regardless of how the agent ended (`DONE`, `PLAN DONE`, `FAILED...`, etc.). The user now
wants to split that case:

- **Unread + non-failed terminal** → angel smiling face (😇).
- **Unread + failed terminal** → devil smiling face (😈).

The "Failed" status family is canonically defined in `src/sase/agent/status_buckets.py:88` as
`status_text.startswith("FAILED")` — there are multiple FAILED variants (e.g. `FAILED`, `FAILED CRASH`, etc.), and they
all share that prefix. We will mirror that prefix check (or call `status_bucket_for_values`) so we do not under-count
failure modes.

## Goal

Replace the single unread-completed marker with two status-aware markers, keeping the rest of the runtime-suffix
rendering (positioning, styling lifecycle, ticking precedence, user-paused fallback) untouched.

| Condition                                   | Marker |
| ------------------------------------------- | ------ |
| Unread, not ticking, status starts `FAILED` | 😈     |
| Unread, not ticking, any other status       | 😇     |
| (Ticking)                                   | 🏃‍♂️     |
| (User-paused, not unread)                   | ✋     |

The user-paused and running cases keep their existing precedence rules in `build_runtime_suffix`.

## Files involved

**Marker source of truth** (single file, three constant slots needed instead of two):

- `src/sase/ace/tui/widgets/_agent_list_render_layout.py`
  - Line 44: rename `_RUNTIME_UNREAD_COMPLETED_MARKER` → split into two constants. Recommended naming:
    - `_RUNTIME_UNREAD_DONE_MARKER = "😇 "`
    - `_RUNTIME_UNREAD_FAILED_MARKER = "😈 "`
  - Line 45: keep `_RUNTIME_UNREAD_COMPLETED_MARKER_STYLE = "#5FD7FF"` — rename to `_RUNTIME_UNREAD_MARKER_STYLE` and
    reuse it for both glyphs. Emoji glyphs render in their intrinsic colors in modern terminals; the foreground style
    only affects the trailing space. Keeping one style minimizes the diff and preserves the established color-family
    separation between suffix variants.
  - In `build_runtime_suffix` (lines 86–122), the four append sites currently use the single
    `_RUNTIME_UNREAD_COMPLETED_MARKER`. Introduce a small helper, e.g.

    ```python
    def _unread_marker(agent: Agent) -> str:
        return (
            _RUNTIME_UNREAD_FAILED_MARKER
            if (agent.status or "").startswith("FAILED")
            else _RUNTIME_UNREAD_DONE_MARKER
        )
    ```

    and use it (with `.rstrip()` at the two no-trailing-elapsed sites). This avoids duplicating the FAILED check four
    times. Alternatively, call `status_bucket_for_values(agent.status) == "Failed"` from `status_buckets.py` for
    semantic alignment with the rest of the codebase — preferred, because it keeps "what is FAILED?" defined in one
    place.

**Failed-status check site** (no edits expected — only a reference):

- `src/sase/agent/status_buckets.py:88` — `status_text.startswith("FAILED")` returns `"Failed"` from
  `status_bucket_for_values`. We call this rather than rolling our own prefix check so future additions to the failure
  family (e.g. `FAILED RETRY`) are automatically picked up. This means `_agent_list_render_layout.py` will gain a new
  import of `status_bucket_for_values`.

**Tests that assert on the literal emoji** (must change `🙂` → either `😇` or `😈`, splitting where needed):

- `tests/ace/tui/widgets/test_agent_list_runtime_rendering.py`
  - Existing `🙂` assertions at ~lines 106, 121, 143, 203, 355, 364, 376 cover non-FAILED rows (`status="DONE"`). Update
    each `🙂` → `😇`.
  - Add a new unit test for the FAILED case asserting `😈` appears in the suffix when an unread agent has
    `status="FAILED"` (and another for a `FAILED CRASH`-style prefix, to lock in the prefix check). Mirror the structure
    of `test_format_agent_option_unread_finished_suffix_has_completed_marker` and
    `test_format_agent_option_unread_terminal_suffix_uses_completed_marker`.
- `tests/ace/tui/widgets/test_agent_render_cache.py`
  - Lines 335, 450, 452: same `🙂` → `😇` swap; these all use a default (non-FAILED) agent.

**Docs**:

- `docs/ace.md:527` — prose mentions "`🙂` marker in the same suffix slot". Update to describe the new split:
  unread-completed rows use 😇 by default and 😈 when the agent finished in a FAILED state.

**Visual snapshots**:

- `tests/ace/tui/visual/snapshots/png/` — regenerate via `just test-visual --sase-update-visual-snapshots`. Existing
  unread fixtures use DONE, so their diffs should be a single-glyph swap from 🙂 to 😇. Inspect each diff under
  `.pytest_cache/sase-visual/` to confirm only the marker pixels changed. No new FAILED-row snapshot is required unless
  the unit-test coverage above is judged insufficient by review.

**Out of scope** (intentionally untouched):

- The running (`🏃‍♂️`) and user-paused (`✋`) markers — those rules don't change.
- BY_STATUS bucket banner glyphs (`▲ ▶ ⏳ ✗ ✓`) in `status_buckets.py`. The bucket banner already uses `✗` for Failed;
  we're not unifying it with the row marker.
- The mark / approve / hidden / bead context glyphs in `_agent_list_styling.py`.
- Rust `sase-core` — these markers are pure Python presentation state.
- Historical SDD records under `sdd/tales/`, `sdd/prompts/`. They describe past decisions; rewriting them makes history
  lie.

## Edge cases & precedence

The four append sites in `build_runtime_suffix` cover these branches. Confirm the new logic preserves them:

1. **No ts, no elapsed, unread** → marker only (`.rstrip()` form). FAILED → `😈`, else `😇`.
2. **Has elapsed, ticking** → running `🏃‍♂️`. Unread never wins over ticking — even for a FAILED row that is somehow still
   ticking (would be unusual but possible transiently), the running marker still takes the slot. This matches existing
   behavior and we keep it.
3. **Has elapsed, not ticking, unread** → marker with trailing space, followed by elapsed. FAILED → `😈 `, else `😇 `.
4. **Has elapsed, not ticking, paused (and not unread)** → `✋`. Unread wins over paused (existing rule in
   `show_user_paused_marker`), which is fine — a FAILED row should never also be a "paused awaiting input" row in
   practice, but the precedence ordering keeps unread-failed correctly showing `😈`.
5. **Has ts but no elapsed, unread** → marker only (`.rstrip()` form), same FAILED split.

## Implementation outline

1. Edit `src/sase/ace/tui/widgets/_agent_list_render_layout.py`:
   - Rename `_RUNTIME_UNREAD_COMPLETED_MARKER` → introduce `_RUNTIME_UNREAD_DONE_MARKER = "😇 "` and
     `_RUNTIME_UNREAD_FAILED_MARKER = "😈 "`.
   - Rename `_RUNTIME_UNREAD_COMPLETED_MARKER_STYLE` → `_RUNTIME_UNREAD_MARKER_STYLE` (value unchanged: `#5FD7FF`).
   - Import `status_bucket_for_values` from `sase.agent.status_buckets`.
   - Add small `_unread_marker(agent)` helper that returns the FAILED or DONE glyph based on the bucket.
   - Replace the four call sites to use the helper (with `.rstrip()` where needed) and the renamed style constant.
2. Update assertions in:
   - `tests/ace/tui/widgets/test_agent_list_runtime_rendering.py` (`🙂` → `😇`), plus two new tests covering the
     FAILED-prefix case.
   - `tests/ace/tui/widgets/test_agent_render_cache.py` (`🙂` → `😇`).
3. Update the prose in `docs/ace.md` (line ~527) to describe the new split.
4. Regenerate visual snapshots: `just test-visual --sase-update-visual-snapshots`, inspect diffs under
   `.pytest_cache/sase-visual/`.
5. Run `just check` to validate lint + types + tests.

## Validation plan

- `just check` passes (lint, mypy, fast pytest, visual snapshots).
- Launch `sase ace` against a project with at least one unread completed agent (DONE) and at least one unread FAILED
  agent. Confirm 😇 and 😈 render in the runtime-suffix slot respectively, while running (🏃‍♂️) and paused (✋) rows are
  unaffected.
- Spot-check a row that is both unread and ticking — `is_ticking=True` still wins and the running marker takes the slot
  (no smiley shown). This is unchanged behavior we intend to keep.
- Spot-check a `FAILED CRASH`-style status (prefix match) renders 😈, not 😇.

## Open question for the user

The plan picks **😇** ("smiling face with halo", U+1F607) and **😈** ("smiling face with horns", U+1F608) — the
angel/devil smileys you described. Both are single codepoints and render in their intrinsic yellow/purple at terminal
sizes. If you'd prefer different glyphs (e.g. `👼` baby-angel face, or `👿` angry-devil-face for a stronger failure
read), say so before I start editing. Otherwise I'll proceed with 😇 / 😈 and keep the marker style at `#5FD7FF`.
