---
create_time: 2026-06-20 17:07:10
status: wip
prompt: sdd/prompts/202606/complete_sase_52_alt_directive_predicate.md
---
# Complete sase-52 Alt Brace Predicate Verification

## Context

Verification of bead `sase-52` found that the main Rust parser, ACE highlighting, ACE editing, Neovim highlighting,
Neovim editing, and docs all implement the `%{A | B}` alt shorthand. One remaining gap exists in the Python quick
predicate `has_alt_directive()`: it detects `%{...}` only at start-of-line or after whitespace, while the parser accepts
directive-valid openings after `(`, `[`, `{`, `"`, and `'` as well.

This matters because `has_alt_directive()` is used as a launch-routing predicate before full fan-out planning. A prompt
like `(%{a | b})` currently splits correctly when planned directly but may not route through fan-out where the quick
predicate is used.

## Plan

1. Update `src/sase/xprompt/_directive_alt.py` so `has_alt_directive()` reuses the same directive-valid regex shape as
   `_ALT_DIRECTIVE_RE`, while still protecting fenced blocks and disabled regions.
2. Add tests in `tests/test_directives_has_helpers.py` for brace shorthand after bracket and quote opener contexts, and
   keep a negative test for word-adjacent `x%{...}`.
3. Run the focused Python tests for directive splitting, directive helper detection, ACE editing/highlighting, and alt
   span inspection.
4. Run the relevant `sase-core` and `sase-nvim` targeted tests from the epic plan to confirm the cross-repo work remains
   sound.
5. Update the epic plan frontmatter status to `done`, close bead `sase-52`, then run `just pyvision`.
