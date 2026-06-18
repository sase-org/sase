---
create_time: 2026-06-18 10:05:52
status: done
prompt: sdd/prompts/202606/bead_search_highlight.md
---
# Plan: Make `sase bead search` match highlighting readable

## Problem

The `sase bead search` command highlights the matched query substring in its `compact` output, but the highlight is hard
to read. On a typical dark-background terminal the matched text appears as light/near-white text sitting on a yellow
block — low contrast, and the eye can't pick the match out of the surrounding text.

## Root cause

Highlighting is rendered by the Rust core (the `bead` read commands are dispatched and rendered entirely in `sase-core`;
see the `rust_core_backend_boundary` rule). In `../sase-core/crates/sase_core/src/bead/cli.rs`:

```rust
const ANSI_HIGHLIGHT: &str = "\x1b[1;43m";   // bold + yellow BACKGROUND, no foreground
const ANSI_RESET:     &str = "\x1b[0m";

fn highlight_matches(text, query, color) {
    ...
    push(ANSI_HIGHLIGHT);  // \x1b[1;43m
    push(matched_text);
    push(ANSI_RESET);      // \x1b[0m
    ...
}
```

Three problems, in order of impact:

1. **No explicit foreground color (primary).** `\x1b[1;43m` sets only a yellow _background_ and bold. The matched
   characters keep the terminal's _default_ foreground — light gray/white on a dark theme — so it's light-on-yellow,
   which is exactly the "hard to read" complaint. Contrast depends on the user's theme and is poor on the common case.
2. **Bold on a filled background reads as muddy** and, on the dimmed snippet line, fights the surrounding `dim`
   attribute.
3. **Full reset closes the highlight.** The compact snippet line is wrapped in `dim` (`\x1b[2m … \x1b[0m`), but each
   highlighted match ends with a _full_ reset `\x1b[0m`, which also clears the dim. So everything in the snippet _after_
   the first match loses its dim and renders at full brightness — visually inconsistent.

The Python fallback handler (`src/sase/bead/cli_query.py`) emits **plain text with no color at all**, so it has no
readability problem and needs no change. This plan is Rust-core-only.

## Goal

Make a search match instantly legible and pleasant to scan, on both dark and light terminal themes, without disturbing
the rest of the compact layout (colored status icon, bold-blue id, dimmed snippet).

## Design

### The highlight style (recommended)

Switch from "background only" to an explicit **foreground + background pair with guaranteed contrast**: dark ink on a
yellow highlight — the universally readable "highlighter pen" look — and drop the bold.

- Start: `\x1b[30;43m` (black foreground on yellow background).
- Close: a **scoped** reset `\x1b[39;49m` (restore default foreground + background only) instead of the full `\x1b[0m`.
  This fixes problem 3: an enclosing `dim` on the snippet line survives the match, so the whole snippet stays uniformly
  dimmed.

Because both foreground and background are pinned, contrast no longer depends on the user's theme: it's dark text on
yellow everywhere. This is the smallest change that addresses all three problems.

Concretely in `cli.rs`:

- `ANSI_HIGHLIGHT` becomes `"\x1b[30;43m"` (was `"\x1b[1;43m"`).
- Add `ANSI_HIGHLIGHT_RESET = "\x1b[39;49m"` and use it as the closing sequence inside `highlight_matches` (instead of
  `ANSI_RESET`). Other styles (status icon, id, dim) keep using the existing `ANSI_RESET`.

### Alternatives considered (a quick decision to confirm)

- **Reverse video** — start `\x1b[7m`, close `\x1b[27m`. Swaps the terminal's own fg/bg, so it adapts to any theme
  automatically and is always readable. The most theme-robust option and even simpler, but it renders the match as a
  solid block of the user's foreground color, which can look "loud" when several matches appear on one line. Strong
  runner-up.
- **Bold colored foreground, no background** — e.g. grep-style bold red `\x1b[1;31m` or bold yellow `\x1b[1;33m`.
  Subtlest and most consistent with the rest of the palette (which uses no backgrounds), but a foreground-only highlight
  is easy to miss when scanning and can blend with the already-colored id/status.

Recommendation: **black-on-yellow** (keeps the familiar highlight semantics, guarantees contrast, minimal diff). If
you'd prefer the theme-adaptive look, we switch to reverse video — same files, same test, trivial to swap.

## Files to change (all in `../sase-core`)

- `crates/sase_core/src/bead/cli.rs`
  - Update the `ANSI_HIGHLIGHT` constant; add `ANSI_HIGHLIGHT_RESET`.
  - Use the scoped reset in `highlight_matches`.
  - Update the golden test `search_compact_color_always_highlights_matches`, which currently asserts
    `outcome.stdout.contains("\x1b[1;43mAuth\x1b[0m token")`, to the new sequence (`\x1b[30;43mAuth\x1b[39;49m token`).
    Optionally add a small assertion that a snippet match keeps the surrounding dim intact, to lock in the problem-3
    fix.

No Python changes: the fallback is intentionally plain text, and this is a pure rendering change with no binding/API
surface change (no `sase-core-rs` version bump required for the API; the new rendering reaches the `sase` repo via the
normal `just rust-install` editable build, and CI's pinned wheel picks it up on the next `sase-core` release).

## Verification

- `just rust-check` and `just rust-test` in `../sase-core` (covers the updated golden test).
- Manual smoke against a seeded store: `sase bead search <term> --color always` and confirm the match is dark ink on
  yellow and easy to read; check a result whose match is in the snippet to confirm the dim stays uniform across the
  line; confirm `--color never` and JSON output are unaffected.
- In the `sase` workspace, `just rust-install` then `sase bead search <term>` to eyeball the real terminal output
  end-to-end.

## Out of scope

- Restyling the rest of the compact layout (status icon colors, bold-blue id, the dim snippet) — only the match
  highlight is the readability problem.
- Any change to `json` (never colored) or `full` (reuses the `show` renderer) output.
- The Python fallback's lack of color — it's plain by design and consistent with the existing `list`/`show`/`ready`
  fallbacks.

## Risks

- **Theme edge cases**: pinning black-on-yellow is robust on standard dark/light themes; a user with an unusual yellow
  could find it bright, but it is strictly more readable than today's default-fg-on-yellow. Reverse video is the
  fallback if a theme-adaptive look is preferred.
- **Golden test drift**: the one test that pins the exact escape bytes must be updated in the same change; it's the only
  place the sequence is asserted.
