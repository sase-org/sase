---
create_time: 2026-07-03 14:20:27
status: wip
prompt: sdd/prompts/202607/fix_models_panel_description_strip.md
---
# Fix the Invisible Models-Panel Alias Description Strip

## Problem

The model-alias descriptions feature (planned in `sdd/tales/202607/model_alias_descriptions.md`, implemented in
`72c62642a` "feat: Add support for custom model aliases", reshaped by `8b0ff2c9f` "feat!: unify model alias config") is
fully wired end-to-end — config schema, `model_alias_description()` policy, `AliasView.description`,
`build_alias_views()`, and the Models panel's `#models-panel-description` strip with mount/refresh/highlight handlers —
yet **no description has ever been visible on the panel**. The strip renders as its `border-top` separator line plus a
blank padding row, with zero text, for every alias (including builtin aliases like `default`, whose descriptions are
fixed, code-owned strings that require no config at all).

## Root Cause (verified empirically, not speculative)

`src/sase/ace/tui/styles.tcss` gives the strip a border-box height that leaves **zero rows for content**:

```tcss
#models-panel-description {
    height: 2;              /* total widget height (border-box) */
    border-top: solid $secondary;   /* consumes 1 of the 2 rows */
    padding-top: 1;                 /* consumes the other row  */
    ...
}
```

Textual's default `box-sizing` is `border-box`: `height` _includes_ border and padding. So the content area is
`2 - 1 (border-top) - 1 (padding-top) = 0` rows, and the Static's text is entirely clipped. Verified with a minimal
Textual 8.2.8 pilot app using this exact rule block: the widget reports `content_size = Size(width=60, height=0)`;
changing `height: 2` to `height: 4` yields `content_size.height == 2` and the text renders.

Supporting evidence:

- The committed golden `tests/ace/tui/visual/snapshots/png/models_panel_default_120x40.png` shows the bug directly: the
  test fixture pins `default` with description `"Model used when a prompt has no %model directive."` and `fast` with
  `"Quick low-cost follow-up agents."`, yet the golden shows an empty strip (separator lines with no text) — identical
  to what the live TUI shows.
- `git log -L` on the rule block shows `height: 2` + `border-top` + `padding-top: 1` was introduced together in
  `72c62642a` and never changed: the feature was born invisible. (The originating plan document itself specified a
  "fixed `height: 2`" strip _and_ a `border-top`, an internally inconsistent spec under border-box sizing; the
  implementation copied it faithfully.)
- Why no test caught it: `tests/test_models_panel.py::test_panel_description_strip_updates_on_highlight` asserts the
  Static's **content** (`description.content.plain`), which is set correctly — nothing asserts the widget's rendered
  (laid-out) size. The PNG goldens _do_ capture the bug, but they were regenerated as part of the same commit that
  introduced it, so the empty strip became the expected image.

## Design

### 1. The CSS fix (the whole runtime fix)

In `src/sase/ace/tui/styles.tcss`:

- `#models-panel-description`: `height: 2` → `height: 4`, with a short comment noting the border-box math (1 border + 1
  padding + 2 content rows) so the next reader doesn't "simplify" it back. Keeping a fixed height (rather than `auto`)
  preserves the original design intent: zero layout shift while j/k-navigating between aliases with different
  description lengths.
- `#models-panel-container`: bump `max-height` so the now-2-rows-taller strip cannot push the footer out of the modal
  when the alias list is at its 22-row cap. Full-budget arithmetic (implementer should re-verify): container border
  (2) + container padding (2) + title + margin (2) + list cap (22) + strip margin + height (1 + 4 = 5) + footer margin +
  border + padding + text (4) = **37**. The current `33` was already 2 rows short of the pre-fix budget, so this also
  corrects that latent clipping. Realistic panels (~10 rows) are unaffected either way.

No Python changes are needed: `_description_text_for_view()`, the highlight handler, `_update_description_strip()`, and
the data layer (`model_alias_description`, `AliasView.description`) are all correct at HEAD. Descriptions with a
2-line-max budget are already guaranteed by the schema's 160-char cap on custom descriptions (2 × 78 content columns).

### 2. Regression test that would have caught this

Extend `tests/test_models_panel.py` (same pilot style as the existing highlight test) with a layout-level assertion:
after mounting `ModelsPanel` with pinned views, assert the strip widget's rendered geometry and visibility —
`query_one("#models-panel-description").content_size.height == 2` (a laid-out, non-zero content area), in addition to
the existing content assertions. This closes the exact gap that let the bug ship: content set ≠ content visible.

### 3. Visual goldens — coordinate with the in-flight goldens plan

The fix intentionally changes the two Models-panel goldens (`models_panel_default_120x40.png`,
`models_panel_overrides_120x40.png` — the fixtures already pin descriptions, so the new renders will finally show the
strip text, including the described `fast` user alias and, in the default view, the builtin `default` description). The
`models_panel_edit_preview_120x40.png` golden does not involve `ModelsPanel` and is unaffected by the strip.

This interacts with the pending `sdd/tales/202607/fix_models_panel_visual_goldens.md` plan (status wip), which
established that these same goldens are currently macOS-corrupted, that macOS hosts cannot produce canonical renders
(cairo/Quartz ignores `FONTCONFIG_FILE`), and that the correct workflow is to adopt CI's `actual.png` artifacts as
goldens. Consequence for this change:

- Do **not** regenerate goldens locally on a macOS host.
- Land this CSS fix + regression test, let CI's `visual-test` job produce the post-fix `actual.png` renders, then adopt
  those via `gh run download <run-id> --name ace-visual-artifacts` and copy them over the two goldens (inspect first:
  Fira Code glyphs, continuous box borders, and — new — visible description text in the strip).
- Sequencing note: if the goldens-fix plan lands first, its adopted goldens will contain the _empty_ strip and this
  change simply re-adopts fresh post-fix CI actuals for the two Models-panel files; if this change lands first, the
  goldens-fix adoption should be taken from a CI run that includes this fix. Either order works — the invariant is that
  the final committed goldens come from a CI run containing this CSS fix.

## Verification

- `just install`, then `just check` (lint + mypy + fmt clean).
- Targeted tests: the new layout regression test plus the existing Models-panel suites (`tests/test_models_panel.py`,
  `tests/llm_provider/test_alias_view.py`).
- Manual: `sase ace` → `,m` → confirm the strip shows the builtin description for `default` immediately on open, updates
  on j/k, shows configured descriptions for any `model_aliases.custom` alias, and shows the amber "no description - set
  llm_provider.model_aliases.custom.<name>.description" hint for a custom-sourced alias without one — all with no layout
  shift while navigating.
- CI: the two updated goldens go green via the CI-adoption workflow described above (local macOS visual runs remain
  environmentally non-canonical, per the goldens plan).

## Out of Scope

- The macOS golden-regeneration guard and docs (Steps 2–3 of `fix_models_panel_visual_goldens.md` — separate wip plan).
- The chezmoi `sase.yml` migration to the unified `model_aliases.builtin`/`.custom` shape (separate wip plan,
  `chezmoi_model_aliases_migration.md`); irrelevant here since builtin descriptions are code-owned and the strip is
  invisible regardless of config shape.
- Any change to description content, the `d`/Describe flow (removed by design in `8b0ff2c9f`), or panel row rendering.

## Risk

Minimal: two numeric CSS values plus one test. The only behavioral change is the modal being 2 rows taller and the strip
actually showing its text. Worst case is a mis-tuned `max-height`, which the full-budget arithmetic above and the manual
`,m` check cover.
