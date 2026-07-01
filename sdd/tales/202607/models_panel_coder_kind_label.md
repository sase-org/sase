---
create_time: 2026-07-01 07:46:01
status: done
prompt: sdd/prompts/202607/models_panel_coder_kind_label.md
---
# Plan: Show `coder` instead of `<provider> coder` in the Models panel kind column

## Goal

On the ace **Models** panel (leader `,m`), the far-left "kind" column currently renders each `<provider>_coder` alias as
`"<provider> coder"` (e.g. `claude coder`, `codex coder`, `qwen coder`, and the truncated `opencode cod…`). Change it so
these rows show just `coder` in that column.

The provider is not lost: the second column already shows the full alias name (`claude_coder`, `codex_coder`, …), so
`coder` in the kind column is unambiguous.

## Product context / motivation

- The far-left column is a small "kind" badge — `default`, `role`, `<provider> coder`, `user`. Repeating the provider in
  the kind badge is redundant because the very next column spells out the full `<provider>_coder` alias name.
- Dropping the provider prefix also removes the awkward truncation currently seen for longer providers (e.g.
  `opencode cod…`), since every provider-coder row becomes the short, uniform label `coder`.

## Scope

This is a **presentation-only** change in the TUI layer. The underlying alias data model is untouched: `AliasView.kind`
stays `"provider_coder"` and `AliasView.name` stays `"<provider>_coder"`. Only the human-readable badge text produced
for that kind changes.

Because only the TUI badge-label formatting changes (not shared domain/back-end behavior), this does **not** cross the
Rust core backend boundary — no `sase-core` changes are required.

## Non-goals

- Do **not** change the kind badge color/style. The `provider_coder` styling entry (a distinct lavender/purple) is keyed
  on `view.kind` and should stay as-is, so these rows remain visually distinguishable from the `role` rows even though
  both may now read differently in the text.
- Do **not** change the alias names, sorting, kind classification, or any other column (the `<provider>_coder` alias
  name still appears in the name column).
- Do **not** shrink the kind-column width. Keeping the existing fixed width preserves the alignment of every downstream
  column across all rows; retightening the layout is out of scope for this request.
- Do **not** touch unrelated surfaces that happen to build a `"<provider> coder"`-style string in a different context
  (e.g. the directive-completion "coder follow-up model" hint). Those are separate features and are not part of the
  Models panel kind column.

## Relevant code (already located)

- **The one place that builds the label** is the kind-label helper in the Models panel modal
  (`src/sase/ace/tui/modals/models_panel.py`). It special-cases the `provider_coder` kind: it strips the `_coder` suffix
  off the alias name to recover the provider and returns `f"{provider} coder"`. All other kinds are looked up in a small
  static `_KIND_LABELS` dict (which today has entries for `default` / `role` / `user` only — `provider_coder` is
  intentionally absent because of the special case).
- The label helper is called from the row renderer (`_render_alias_row`) when building each option row; the style is
  looked up separately by `view.kind`, so styling is unaffected by the label change.
- The provider-suffix constant used by the special case is imported from `sase.llm_provider.config`.

## Design / implementation approach

Remove the `provider_coder` special case entirely and make it an ordinary static-label lookup:

1. **Add `provider_coder` to the static kind-label map** in `src/sase/ace/tui/modals/models_panel.py`, mapping it to
   `"coder"`. This makes the label map symmetric with the existing kind-style map (which already lists all four kinds).
2. **Simplify the kind-label helper** so it no longer branches on `provider_coder` and no longer reconstructs the
   provider from the alias name — it becomes a plain lookup in the label map (falling back to the raw kind string, as it
   already does for unknown kinds).
3. **Drop the now-unused import** of the provider-coder suffix constant from `sase.llm_provider.config` in this module
   (it was only used by the removed special case), keeping the sibling `DEFAULT_MODEL_ALIAS_NAME` import that is still
   used elsewhere in the file. This keeps `just lint` (ruff) clean.

This keeps the change minimal and localized to the single rendering module, with no new behavior branches.

## Tests to update

1. **Unit test** in `tests/test_models_panel.py`: there is a test asserting the provider-coder kind label equals
   `"codex coder"`. Update its assertion to expect `"coder"`, and rename it so the name reflects the new behavior (it no
   longer "strips a suffix" to build a provider-prefixed label — it now just shows `coder`).

2. **Visual PNG snapshots** for the Models panel (`tests/ace/tui/visual/test_ace_png_snapshots_models_panel.py`): both
   the "no overrides" and "overrides active" fixtures include `claude_coder` and `codex_coder` provider-coder rows, so
   both golden PNGs will change (the kind column for those rows goes from `claude coder` / `codex coder` to `coder`).
   Regenerate the two goldens under `tests/ace/tui/visual/snapshots/png/` by running the visual suite with the update
   flag (`just test-visual --sase-update-visual-snapshots`), then confirm the accepted diffs are exactly the intended
   kind-column text change and nothing else.

No new tests are strictly required, but the existing unit test above becomes the regression guard for the new label.

## Verification

- `just install` (ephemeral workspace may have stale deps), then `just check` (ruff + mypy + fast test suite).
- `just test-visual` to confirm the regenerated Models-panel goldens pass.
- Manual sanity check via `sase ace` → `,m`: confirm every `<provider>_coder` row shows `coder` in the far-left column,
  the name column still shows the full `<provider>_coder` name, the badge color for those rows is unchanged, and no row
  is truncated in the kind column anymore.

## Risks / edge cases

- **Low risk.** The change is a single label string in one module plus its test and two golden images.
- The `role` alias `coder` will now read `role` in the kind column while the provider-coder rows read `coder`; they
  remain distinguishable by the name column and the (unchanged) distinct kind colors. This matches the requested
  behavior.
- Watch for the unused-import lint error if the suffix-constant import is not removed after deleting the special case.
