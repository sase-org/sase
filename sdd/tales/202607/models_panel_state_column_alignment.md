---
create_time: 2026-07-01 08:00:19
status: done
prompt: sdd/prompts/202607/models_panel_state_column_alignment.md
---
# Plan: Align the Models panel state column

## Goal

On the ace **Models** panel (leader `,m`), make the far-right state/provenance column align vertically for every row.
Rows currently render as:

```text
<kind> <alias name> <PROVIDER(model)>   <state>
```

The first two columns are fixed-width, but the provider/model badge is not. As a result, the state column starts in a
different cell for `CODEX(o3)`, `CLAUDE(opus)`, and `CLAUDE(haiku)`. The fix should make `implicit`, `configured`,
`override · ...`, and `implicit -> @default` start at the same cell across the panel.

## Product context

The Models panel is a dense operational surface for quickly comparing aliases, effective provider/model targets, and
temporary override state. The state/provenance tag is the rightmost scan column, so ragged starts make it harder to
compare rows at a glance. The previous `provider_coder -> coder` change fixed the left side of the row; this change
finishes the row alignment by treating the provider/model badge as a real column too.

## Scope

This is a presentation-only TUI change in `src/sase/ace/tui/modals/models_panel.py`.

The underlying alias model stays unchanged:

- `AliasView.kind`, `AliasView.name`, `provider`, `model`, configured state, and override state are not changed.
- Sorting, selection, edit/reset/override behavior, and persistence are not changed.
- Provider/model badge colors and markup continue to come from `provider_model_badge_markup`.

This does not cross the Rust core backend boundary because it only changes local Textual/Rich row composition.

## Design

Introduce an explicit provider/model display column between the alias-name column and the state column.

1. Build the provider/model badge as a `rich.text.Text` value before appending it to the row, instead of appending the
   raw `Text.from_markup(...)` directly.
2. Compute one provider/model column width for the current set of visible alias rows when `ModelsPanel._build_options`
   rebuilds the options.
   - Use Rich cell widths, not Python string length, so any wide glyphs or future provider badges remain measured
     correctly.
   - Size the column to the widest provider/model badge currently visible, capped by a maximum that fits the existing
     84-column modal budget.
   - Keep a small maximum-width cap so very long custom model names cannot push the state column out of view. Overlong
     provider/model badges should ellipsize inside their own column.
3. Update `_render_alias_row` to accept the computed provider/model column width and append a fitted badge:
   - preserve provider/model styling;
   - truncate with ellipsis only when the badge exceeds the cap;
   - pad shorter badges to the chosen column width;
   - append the existing fixed gap and then the state tag.
4. Keep the existing fixed kind and alias-name widths. The final row shape becomes:

```text
<kind fixed> <alias fixed> <provider/model fitted>   <state>
```

For the current visual fixture data, this should align the state column at the widest provider/model badge in the
fixture (`CLAUDE(haiku)`) instead of allowing short `CODEX(o3)` rows to start early.

## Edge cases

- A row with no provider/model badge should still reserve the computed provider/model column width so its state tag
  aligns with rows that do have badges.
- If every row lacks a provider/model badge, the provider/model column can collapse to zero width and the state column
  still aligns across the panel.
- Long provider/model labels should not hide the state column. They should be ellipsized within the provider/model
  column cap.
- The state tag itself remains variable length; this plan aligns the start of the rightmost column, not the right edge
  of every state string.

## Tests

Update `tests/test_models_panel.py` with focused regression coverage:

1. Add a unit test that renders at least two rows with different provider/model badge widths using the same computed
   provider/model column width, then asserts the state tag starts at the same index/cell in each rendered row.
2. Add or extend coverage for a long provider/model label to ensure the state tag is still present and aligned after the
   badge is ellipsized.
3. Keep the existing row-content test asserting that alias name, provider/model label, and state text are present for
   normal-width labels.

Update the Models panel PNG snapshots:

- `tests/ace/tui/visual/snapshots/png/models_panel_default_120x40.png`
- `tests/ace/tui/visual/snapshots/png/models_panel_overrides_120x40.png`

The expected visual change is that the state/provenance tags line up across rows in both the no-overrides and
overrides-active fixtures. No unrelated snapshot changes should be accepted.

## Verification

After implementation:

1. Run `just install` first, per this repo's ephemeral-workspace instructions.
2. Run the focused unit coverage, for example:

   ```bash
   just test tests/test_models_panel.py -k 'render_alias_row or provider_model'
   ```

3. Regenerate only the Models panel visual snapshots with the update flag, then inspect the diff and restore any
   unrelated PNG rewrites.
4. Run the focused visual test without the update flag:

   ```bash
   just test-visual tests/ace/tui/visual/test_ace_png_snapshots_models_panel.py
   ```

5. Run the required full repository check:

   ```bash
   just check
   ```

## Risks

- The main risk is choosing a provider/model column cap that is too wide for the existing modal budget or too narrow for
  common model names. Use the current modal width, fixed left-column widths, fixed gap, and longest state tag
  (`override · until cleared`) to choose a cap that leaves the state column visible.
- Rich `Text.truncate(..., pad=True)` should be used on a copy of the badge text so provider/model styling survives and
  raw markup never leaks into rendered rows.
- Visual snapshot regeneration can rewrite unrelated PNGs. Inspect the diff and keep only the two Models panel golden
  changes that correspond to the intended alignment fix.
