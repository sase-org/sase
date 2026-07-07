---
create_time: 2026-07-07 18:00:51
status: done
prompt: sdd/prompts/202607/close_sase_5i_parity_and_test_gaps.md
---
# Plan: Close Out Epic sase-5i — Fix vcs_ref Parity Divergence + Fill Phase 3 Test Gaps

## Context

Epic `sase-5i` (VCS-Agnostic Ref Completion for `#gh:` / `#git:`) has all six phase beads closed, and verification
confirms the feature is implemented end-to-end across sase, sase-github, sase-core, and sase-nvim. Two gaps against the
approved epic plan (`sdd/epics/202607/vcs_ref_colon_completion.md`) remain and must be fixed before the epic bead can be
closed.

### Gap 1 — Python↔Rust parity divergence in the org-chain accept (the real bug)

The epic's Design Principle 4 requires trigger detection and the accept transform to be implemented identically in
Python (`sase`) and Rust (`sase-core`), pinned by a shared golden-vector table that is mirrored byte-for-byte. Today:

- **Behavioral divergence**: for a closed-paren token, chain-accepting an org produces different buffers in the two
  frontends. Given `#gh(sa<CURSOR>) next` and org `sase-org`:
  - Python (`apply_vcs_ref_selection` in `src/sase/xprompt/vcs_ref_completion.py`, chain branch) strips the existing `)`
    → `#gh(sase-org/ next`.
  - Rust (`vcs_ref_replacement_text` in `crates/sase_core/src/editor/completion.rs`) keeps it → `#gh(sase-org/) next`.
- **Table divergence**: the Python `VCS_REF_GOLDEN_VECTORS` and the Rust `vcs_ref_golden_vectors` tables differ in rows
  (different paren/HITL variants, Python-only `#git`/mid-prompt-chain rows, Rust-only after-cursor-text and
  trailing-newline rows) and in the chain `selected_ref` convention (Python rows pass `"sase-org/"`; Rust rows pass
  `"sase-org"` and normalize).

**Resolution — Rust behavior wins; Python changes.** Keeping the `)` is strictly better: the token stays well-formed if
the user abandons the chained repo menu, it matches the terminal-accept principle of reusing an existing paren, and the
epic spec only says chain adds _no_ suffix — it never asks for a deletion. The sase-5h repo trigger only rejects a `)`
_before_ the cursor, so the chained repo menu still opens with the `)` present. This is also the far smaller change: one
branch in Python vs. builder/textEdit range changes in the Rust LSP path.

Concretely:

1. In Python `apply_vcs_ref_selection` chain branch: stop stripping a `)` that follows the ref span, and normalize
   `selected_ref` to end with exactly one `/` (mirror Rust's `vcs_ref_namespace_insertion`: trim trailing slashes,
   append one). Cursor math in the TUI accept (`value_start + len(selected_ref)`) is unaffected.
2. Define one canonical golden-vector table and mirror it byte-for-byte in both languages (`VCS_REF_GOLDEN_VECTORS` in
   `src/sase/xprompt/vcs_ref_completion.py`; the `vcs_ref_golden_vectors` test table in
   `crates/sase_core/src/editor/completion.rs`). The canonical table is the merged, behavior-identical superset of
   today's two tables (all rows use chain refs _without_ a trailing slash, plus one row _with_ a trailing slash to pin
   the normalization in both languages):

   | marked prompt            | workflows | selected_ref | chain | expected                |
   | ------------------------ | --------- | ------------ | ----- | ----------------------- |
   | `#gh:<CURSOR>`           | gh        | sase         | false | `#gh:sase `             |
   | `#gh:sa<CURSOR>`         | gh        | sase         | false | `#gh:sase `             |
   | `Fix #gh:sa<CURSOR> now` | gh        | sase         | false | `Fix #gh:sase now`      |
   | `#gh!!:sa<CURSOR>`       | gh        | sase         | false | `#gh!!:sase `           |
   | `#gh:s<CURSOR>asex`      | gh        | sase         | false | `#gh:sase `             |
   | `#git:sa<CURSOR>suffix`  | git       | sase         | false | `#git:sase `            |
   | `#gh(s<CURSOR>`          | gh        | sase         | false | `#gh(sase)`             |
   | `#gh(s<CURSOR>) next`    | gh        | sase         | false | `#gh(sase) next`        |
   | `#gh??(s<CURSOR>`        | gh        | sase         | false | `#gh??(sase)`           |
   | `#gh:<CURSOR>`           | gh        | sase-org     | true  | `#gh:sase-org/`         |
   | `#gh:<CURSOR>`           | gh        | sase-org/    | true  | `#gh:sase-org/`         |
   | `Fix #gh:sa<CURSOR> now` | gh        | sase-org     | true  | `Fix #gh:sase-org/ now` |
   | `#gh(sa<CURSOR>`         | gh        | sase-org     | true  | `#gh(sase-org/`         |
   | `#gh(sa<CURSOR>) next`   | gh        | sase-org     | true  | `#gh(sase-org/) next`   |

3. The Rust-only trailing-newline row (`#gh:sa<CURSOR>\n` → `#gh:sase \n`) moves out of the golden table into a
   dedicated Rust test documenting the editor-final-newline nuance — this divergence is deliberate sase-5h precedent
   (Rust treats a document-final newline as end-of-input so Neovim keeps the visible trailing space; the TUI has no
   implicit final newline) and therefore cannot live in a byte-identical shared table.

### Gap 2 — Phase 3 promised test coverage that was never written (repo: sase)

The epic's Phase 3 test list includes items that don't exist:

- Widget tests (`tests/ace/tui/widgets/test_vcs_ref_completion.py`): accept of a **ChangeSpec** row (terminal, trailing
  space); **dismiss** (typing a negative such as `~` at ref start clears the menu); **typed-`/` hand-off** (typing `/`
  inside the ref dismisses the ref menu and the repo menu path takes over); **ordering** (`#gh:owner/` opens the repo
  menu, not the ref menu; a non-VCS xprompt tag like `#foo:` still gets today's xprompt-argument behavior).
- PNG snapshots: only the populated all-three-kinds scenario exists (`vcs_ref_completion_panel_120x40.png`). Add the two
  missing scenarios from the plan to `tests/ace/tui/visual/test_ace_png_snapshots_vcs_ref_completion.py`: **no-orgs**
  (`#git:` — border title reads `… · projects & PRs`, no org rows) and **placeholder** (force-open with empty source —
  dim-italic "no known projects, PRs, or organizations" row). Generate goldens with `--sase-update-visual-snapshots` and
  verify with `just test-visual`.

### Explicitly skipped (not a defect)

The epic's Phase 6 "glossary Tier-1 memory entry" is intentionally NOT delivered: per `memory/gotchas.md`, memory files
must never be edited without the user granting permission in the current conversation, and plan-file authorization does
not count. sase-5h set the precedent by reverting exactly such an entry. This is surfaced to the user instead.

## Steps

1. **sase (Python) — parity fix + canonical vectors.** Update the chain branch of `apply_vcs_ref_selection` (keep `)`,
   normalize trailing slash); replace `VCS_REF_GOLDEN_VECTORS` with the canonical table above. The parametrized golden
   test picks the table up automatically.
2. **sase (Python) — Phase 3 test gaps.** Add the four missing widget tests and the two missing PNG snapshot scenarios +
   goldens.
3. **sase-core (Rust) — mirror the canonical table.** Open the linked repo with `sase workspace open`; replace the
   `vcs_ref_golden_vectors` table with the byte-identical canonical table; move the trailing-newline case into its own
   test with a comment explaining the deliberate divergence. No production-code changes expected on the Rust side.
4. **Verify.** sase: `just install`, `just check` (includes visual suite). sase-core: `cargo fmt --check`,
   `cargo test -p sase_core -p sase_xprompt_lsp`.
5. **Close the epic.** `sase bead close sase-5i` (or `sase bead update sase-5i --status closed`).
6. **Post-close checks.** Run `just pyvision` in sase (some symbols are only checked once the epic closes) and fix any
   unused-code findings it reports.
7. **Mark the epic plan done.** Set `status: done` in the frontmatter of `sdd/epics/202607/vcs_ref_colon_completion.md`.
