---
create_time: 2026-05-10 12:33:05
status: done
prompt: sdd/prompts/202605/stop_sign_marker.md
---
# Plan: Swap 🙋 → 🛑 For User-Paused (Stopped) Agent Rows

## Goal

Replace the person-raising-hand marker (`🙋`) currently shown on user-paused agent rows in the ACE TUI with a stop-sign
marker (`🛑`). The user refers to these as "stopped" agents; functionally they are agents whose lifecycle is paused
waiting on a human action (`PLANNING`, `QUESTION`, `WAITING INPUT`).

This is a presentation-only swap. Agent lifecycle, status bucketing, runtime calculation, suffix arbitration order,
ticking behavior, and core/backend code all stay unchanged.

## Current Shape

The 🙋 marker was introduced by `sdd/tales/202605/paused_runtime_emoji.md` (status: done). All live (non-historical)
references are concentrated in three files:

1. `src/sase/ace/tui/widgets/_agent_list_render_layout.py:48` — `_RUNTIME_USER_PAUSED_MARKER = "🙋 "` (with
   `_RUNTIME_USER_PAUSED_MARKER_STYLE = "#FFAF00"` amber on the next line). This is the single source of truth;
   `build_runtime_suffix()` consumes it at lines 92, 113, 124.
2. `tests/ace/tui/widgets/test_agent_list_runtime_rendering.py` — 4 assertions hard-code the literal `🙋` (lines 141,
   158, 173, 192, 204; the last two are negative assertions on rows that should _not_ show the marker).
3. `docs/ace.md:499` — narrative line in the runtime-suffix section describing what `🙋` means.

Other 🙋 hits are in `sdd/prompts/202605/*.md` and `sdd/tales/202605/paused_runtime_emoji.md`. Those are historical
prompt/tale records (frozen artifacts of past work) and are intentionally left alone — rewriting them would distort the
project history.

The suffix-marker arbitration order in `build_runtime_suffix()` stays:

1. Ticking rows: `🏃‍♂️`
2. Unread non-ticking completed rows: `🎉`
3. User-paused rows: `🛑` (was `🙋`)

## Design

### 1. Swap the marker glyph

In `src/sase/ace/tui/widgets/_agent_list_render_layout.py`, change the constant:

```python
_RUNTIME_USER_PAUSED_MARKER = "🛑 "
```

Keep the trailing space — the rendering code at line 88 uses `.rstrip()` for the no-elapsed branch and the raw constant
(with its space) for the with-elapsed branch, mirroring `🏃‍♂️ ` and `🎉 `. The cell-width math in
`assemble_padded_option()` already relies on Rich `cell_len`, which handles the new emoji the same way.

### 2. Recolor to match the glyph (recommended)

The current amber `#FFAF00` was chosen to read as "needs attention" with the raised-hand icon. A stop sign is
canonically red, so the amber styling reads slightly off against a red glyph. Recommendation: change
`_RUNTIME_USER_PAUSED_MARKER_STYLE` to a saturated-but-readable red such as `#FF5F5F` (light enough to remain legible on
dark themes; in the same family as the existing `bold red` error styling without being the exact same token). This is a
small product-design call — if the user prefers to keep amber for continuity, leave the style line untouched.

### 3. Constant name stays

`_RUNTIME_USER_PAUSED_MARKER` describes the semantic role ("user is paused, waiting on a human"), not the glyph. The
semantics did not change, so renaming would only churn imports and tests with no readability win. Leave it.

### 4. Tests

In `tests/ace/tui/widgets/test_agent_list_runtime_rendering.py`, update the literals:

- Line 141: `"13:14:53 · 🙋 5m53s"` → `"13:14:53 · 🛑 5m53s"`
- Line 158: `"🙋"` → `"🛑"`
- Line 173: `"🙋"` → `"🛑"`
- Line 192: negative assertion `"🙋" not in ...` → `"🛑" not in ...`
- Line 204: negative assertion `"🙋" not in ...` → `"🛑" not in ...`

The three positive assertions (PLANNING with elapsed, QUESTION without time, WAITING INPUT without runtime) cover the
two render branches in `build_runtime_suffix()` (with/without elapsed). The two negative assertions guard the
arbitration order against accidentally showing the paused marker on a ticking row or an unread completed row.

No new tests are required — the existing coverage already exercises every branch that touches the marker constant, and
the swap is a literal substitution.

### 5. Docs

In `docs/ace.md:499`, update the prose:

```
… and user-paused rows (`PLANNING`, `QUESTION`, `WAITING INPUT`) use a `🛑` marker while waiting for a human response.
```

That single character is the only doc change needed — surrounding sentences about the suffix slot and the running /
unread markers stay accurate.

## Out Of Scope

- Historical `sdd/prompts/202605/*.md` and `sdd/tales/202605/paused_runtime_emoji.md` references. These are
  point-in-time records and should not be rewritten.
- The status set (`PLANNING`, `QUESTION`, `WAITING INPUT`) that triggers the marker. Unchanged.
- `runtime_suffix_ticks()` and other paused-vs-active arbitration logic. Unchanged.
- Rust core / `sase-core` — this is TUI presentation only; it does not cross the core boundary defined in
  `memory/short/rust_core_backend_boundary.md`.
- Any rename of the `_RUNTIME_USER_PAUSED_MARKER` constant.

## Verification

1. Targeted rendering tests: `uv run pytest tests/ace/tui/widgets/test_agent_list_runtime_rendering.py`
2. Repo-required gate after file edits: `just install && just check`
3. Quick visual smoke (optional): launch `sase ace` against a project with at least one `PLANNING`, `QUESTION`, or
   `WAITING INPUT` row and confirm the suffix shows `🛑` in the slot where `🙋` used to appear.

## Risks

- Cell-width: `🛑` (U+1F6D1) is a standard wide emoji and renders in the same 2-cell slot as `🙋` on every terminal we
  already exercise (`🏃‍♂️`, `🎉`, `🙋`). No layout math changes are needed.
- Color call: if amber is preserved, the row reads as "amber stop sign" which can look like a yield/caution sign rather
  than a true stop. The recommended red style avoids that ambiguity but is the only judgment-call line in this plan —
  flag it during review if desired.
- Theme legibility: a red marker on dark themes is fine; on the rarely-used light theme `#FF5F5F` is still readable but
  if the project later adds explicit theme tokens this constant should migrate alongside the other suffix-marker styles
  rather than picking up its own ad-hoc value.
