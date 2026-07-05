---
create_time: 2026-07-05 18:29:57
status: wip
---
# Fix garbled AXE tab rendering under the `,?` tab guide modal

## Problem

Opening the tab guide modal with `,?` on the AXE tab sometimes garbles the whole screen: base-tab content bleeds through
the modal, modal text shifts left past its own border, and corrupted fragments like `3munsent=0`, `mupdates=0`, and
`ures=0` appear interleaved with the guide content (see screenshot `20260705_175515.png`).

## Root cause

Raw ANSI escape sequences end up as literal characters inside the Rich `Text` that the AXE tab renders, so
Rich/Textual's cell-width math disagrees with what the terminal actually draws.

The full chain:

1. **The lumberjack log file contains raw ANSI escape codes.**
   - `Lumberjack._flush_log_to_file` (`src/sase/axe/lumberjack.py`) exports the console with `export_text(styles=True)`,
     so styled log lines (e.g. the yellow `Tick overrun: ...` line, red error lines) are written to disk with
     `\x1b[33m...\x1b[0m` wrappers.
   - `Lumberjack._append_log_tail` copies raw captured chop output (e.g. the telegram chop's
     `unsent=0 sent=0 failures=0` stats lines, which carry their own color codes) verbatim into the same log.

2. **The semantic renderer keeps the escape bytes.** Commit `848bb6689` introduced
   `src/sase/ace/tui/util/axe_log_renderer.py`, which routes lumberjack log tails through `_render_lumberjack_log` →
   `_highlight_message_body` → `Text(body)`. Unlike the old `Text.from_ansi` path (still used for `source_type="ansi"`),
   plain `Text(body)` does not decode or strip ANSI — the ESC bytes become literal Text content.

3. **Rich counts escape bytes as printable cells; the terminal doesn't.** Verified experimentally:
   `cell_len("\x1b[33munsent=0 sent=0\x1b[0m")` returns 22, but a terminal renders 15 cells. Every escape sequence in a
   rendered row makes Textual think the row is wider than it really is.

4. **The `,?` modal turns the latent mismatch into visible garbage.** With the modal open, the compositor crops the base
   screen's strips at the modal edges. `Strip.crop` slices at cell offsets that include the phantom escape-byte cells,
   so:
   - crops can cut an escape sequence in half (verified: cropping mid-sequence leaves fragments like `\x1b[3` on one
     side and the literal text `3munsent=0` on the other — exactly the corruption in the screenshot), and
   - segments render fewer real cells than Textual accounted for, so everything written after them on the same terminal
     row (the modal border, guide text, the right-hand base strip) shifts left, producing the interleaved bleed-through.

   Without the modal the log lines are usually the last content on their row, so the mismatch only produces invisible
   trailing shift — which is why the AXE tab normally looks fine and the bug appears tied to `,?`.

5. **Why "sometimes":** it only reproduces when the currently visible lumberjack log tail (`RECENT LOG` section rendered
   by `AxeOutputSection.update_lumberjack_overview`) happens to contain ANSI-styled lines. A quiet, plain-ASCII tail
   renders cleanly.

There is a secondary bug with the same root: an ANSI-prefixed header line (e.g. the yellow tick-overrun line starts with
`\x1b[33m[2026-...`) never matches `_LJ_LINE_RE`, so styled lines silently lose their semantic timestamp/name
highlighting even when nothing garbles.

## Fix

Strip ANSI escape sequences (and stray C0 control characters) from the input before the semantic highlighters parse it,
in `src/sase/ace/tui/util/axe_log_renderer.py`. This is squarely within the module's stated design ("colorize ...
instead of relying on whatever ANSI escapes the underlying tool happened to inject") — the stripping step was simply
missing.

Design:

1. Add a module-level sanitizer, e.g. `_strip_control_sequences(s: str) -> str`:
   - Fast bail when `"\x1b" not in s` and no other C0 controls are present, so the common plain-text case costs one
     containment scan.
   - Remove, via precompiled regex: CSI sequences (`\x1b[` params + final byte), OSC sequences (`\x1b]` ... terminated
     by BEL or ST), and remaining two-byte `\x1b<X>` escapes.
   - Remove remaining C0 control characters except `\n` and `\t` (a trailing `\r` from CRLF chop output would otherwise
     survive `_split_lines` and reset the terminal cursor to column 0 — same class of corruption).

2. Apply it in `render_axe_output` on the cache-miss path only, for the semantic source types (`"lumberjack"` and
   `"chop_controlled"`), after `cap_ansi_output` and the cache lookup but before parsing. The `"ansi"` path stays on
   `Text.from_ansi`, which already decodes escapes into styles correctly.
   - Cache behavior is unchanged: the `(size, tail_hash)` key is computed on the raw capped input, so unchanged refresh
     ticks still return the cached parsed `Text` without ever running the sanitizer (per the TUI perf rule: keep
     per-tick fast paths free).

3. No changes to the lumberjack log writer. `export_text(styles=True)` is intentional — the daemon log and other
   consumers render through the ANSI fallback and want the colors, and third-party chop output can always contain ANSI
   regardless of what we write, so the renderer must be robust to it anyway. No changes to the modal either; it is only
   the trigger. This is presentation-only TUI logic, so it stays in this repo (no sase-core boundary crossing).

A useful side effect of stripping before parsing: styled header lines now match `_LJ_LINE_RE` again, restoring semantic
highlighting for the tick-overrun/error lines.

## Tests

Extend `tests/ace/tui/util/test_axe_log_renderer.py` (existing helpers `_render_lumberjack` / `_render_controlled_chop`
and `_styles_at` cover the shape):

1. A lumberjack line wrapped in ANSI (e.g.
   `"\x1b[33m[2026-05-11 12:34:56] [hooks] Tick overrun: took 6.0s but interval is 5s\x1b[0m\n"`) renders with **no**
   `\x1b` in `text.plain`, and `text.cell_len` equals the visible length — this is the regression assertion for the
   garbling.
2. The same ANSI-wrapped header line still gets semantic highlighting (timestamp dim, name gold) — covers the secondary
   `_LJ_LINE_RE` bug.
3. Chop-output-style body with embedded color codes (e.g. `\x1b[33munsent=0 sent=0\x1b[0m`) round-trips to clean plain
   text on both the `lumberjack` and `chop_controlled` paths.
4. A line with a trailing `\r` (CRLF input) renders without the `\r` in `text.plain`.
5. Plain-text input renders byte-identical plain text (fast-bail path keeps the existing
   `test_lumberjack_log_preserves_plain_text` guarantee).

## Verification

- `just install` (fresh workspace), then `just check`.
- Manual: with a lumberjack log tail containing ANSI (a tick-overrun line or telegram chop stats), open the AXE tab and
  press `,?` — the guide modal must render cleanly with the dimmed base screen behind it and no interleaved fragments.

## Files touched

- `src/sase/ace/tui/util/axe_log_renderer.py` — add sanitizer, apply on semantic paths.
- `tests/ace/tui/util/test_axe_log_renderer.py` — regression tests above.
