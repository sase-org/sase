---
create_time: 2026-04-28 10:39:13
status: done
prompt: sdd/prompts/202604/cls_tab_l0_spacing.md
---
# Add vertical space between top-level groups on the CLs tab

## Problem

On the **agents tab**, each top-level (L0) group banner is separated from the previous one by a blank spacer row. This
gives the eye an obvious gutter between e.g. project banners and stops the wall-of-banners feeling when several groups
stack up.

On the **CLs tab**, no such gutter exists. After the recent
`feat(ace): add sibling-root sub-banner under BY_STATUS on the CLs tab` commit, the tree now has two banner levels (L0 =
project/date/status, L1 = sibling-root sub-banner), so banner rows can pile up adjacent to each other with no visual
separation between top-level groups.

The user has asked for the CLs tab to mirror the agents-tab spacing, calling it "vertical space between L1
headings/groups". Throughout this plan I read "L1" as **top-level / first-level** (i.e. `level == 0` in code, matching
the agents-tab L0 spacer behavior). I am **not** proposing to add a spacer between L0 banners and their L1 sibling-root
sub-banners — that pair should stay tightly attached, the way the agents tab keeps its level-1/level-2 sub-banners
attached to their parent. I'll confirm this reading with the user before implementing if there is any doubt.

## Reference: how the agents tab does it

`src/sase/ace/tui/widgets/_agent_list_build.py`, around lines 246–260 of `build_list()`:

```python
banner_seq = 0
spacer_seq = 0
seen_first_l0 = False
for entry in tree:
    if entry.kind == "group" and entry.group is not None:
        if entry.group.level == 0:
            if seen_first_l0:
                spacer = Option(
                    Text(""),
                    id=f"spacer:{spacer_seq}",
                    disabled=True,
                )
                spacer_seq += 1
                widget.add_option(spacer)
                widget._row_entries.append((_BANNER_ROW, None))
            seen_first_l0 = True
        # ... emit the banner option ...
```

Properties of the spacer:

- `Option(Text(""))` — empty cell.
- `disabled=True` — keyboard navigation skips it; nothing can be selected or activated on this row.
- Unique `id` (`spacer:<n>`) — keeps Textual's option-id index unique.
- `_row_entries` gets a sentinel value, so any code that maps option index → entity index treats the row as "not a real
  row".
- Inserted **before** the second and subsequent L0 banners only — the first L0 banner does not get a leading blank line.

## Target site on the CLs tab

`src/sase/ace/tui/widgets/_changespec_list_render.py`, function `render_grouped()`, lines 134–162. The current loop:

```python
banner_seq = 0
for entry in tree:
    if entry.kind == "group" and entry.group is not None:
        group = entry.group
        selectable = group.is_collapsed
        ...
        banner_seq += 1
        row_index = len(widget._row_entries)
        widget.add_option(option)
        widget._row_entries.append(_BANNER_ROW)
        ...
        continue
    ...
```

Notes on the local conventions that differ from the agents tab:

1. `_row_entries` on the CLs widget stores plain ints (`_BANNER_ROW = -1` for banners; the changespec index for CL
   rows). It does **not** use a tuple shape like the agents tab. The spacer must therefore append the bare `_BANNER_ROW`
   sentinel — not `(_BANNER_ROW, None)`.
2. `Text` is not currently imported in this module; we'll need to add `from rich.text import Text`.
3. The L0 banner is the only level we want to gate on. Sibling-root banners have `group.level == 1` and must not trigger
   a spacer.

## Proposed change

Add a spacer-emission block at the top of the `entry.kind == "group"` branch, gated on `group.level == 0`, mirroring the
agents-tab pattern:

```python
banner_seq = 0
spacer_seq = 0
seen_first_l0 = False
for entry in tree:
    if entry.kind == "group" and entry.group is not None:
        group = entry.group
        if group.level == 0:
            if seen_first_l0:
                spacer = Option(
                    Text(""),
                    id=f"cs-spacer:{spacer_seq}",
                    disabled=True,
                )
                spacer_seq += 1
                widget.add_option(spacer)
                widget._row_entries.append(_BANNER_ROW)
            seen_first_l0 = True
        selectable = group.is_collapsed
        ...
```

Implementation notes:

- Use a distinct id prefix (`cs-spacer:` rather than `spacer:`) because the CLs and agents widgets are separate
  `OptionList` instances and there's no real id collision risk, but a different prefix makes spacer rows trivially
  greppable per widget if we ever debug it.
- The spacer row goes **before** the L0 banner is emitted. That keeps the gutter visually attached to the bottom of the
  previous group's contents, which is the same arrangement the agents tab produces.
- `widget._row_widths_by_idx`, `widget._last_row_signature_by_idx`, and `widget._row_render_ctx` are keyed by changespec
  index, not by option index. None of them need entries for spacer rows.
- `widget._banner_at_row` and `widget._banner_row_by_key` are populated only inside the `selectable` branch for real
  banners, so spacer rows correctly stay out of those maps.

## Edge cases I considered

- **Empty tree.** `build_changespec_tree([], ...)` returns `[]` early (line 111–112 of `_tree.py`), and
  `render_grouped()` short-circuits before reaching the loop in practice — but even if it didn't, the loop would not run
  and `seen_first_l0` would stay `False`, so no spacer is emitted. Safe.
- **Single L0 group.** First (and only) L0 banner sees `seen_first_l0 = False` → no leading spacer. Matches agents tab.
- **Collapsed L0 group with no children.** Tree still emits the L0 banner entry; subsequent L0 banner gets a spacer
  above it. Correct.
- **Sibling-root (L1) banners in a row.** They have `group.level == 1`, so the gate `if group.level == 0` skips them
  entirely. The L1 banner stays glued to its parent L0 banner / sibling rows. Correct.
- **Highlight bookkeeping.** `highlighted_row` is computed from `len(widget._row_entries)` at the moment the real banner
  / CL is appended. Because the spacer increments `_row_entries` _before_ the banner, the banner's `row_index` correctly
  accounts for the spacer offset. No off-by-one.
- **Patch path.** The grouped renderer doesn't share the patch-render fast path (per the docstring at the top of
  `render_grouped()` — "the grouped path always does a full rebuild"). Adding spacers does not change that contract.
- **Width calculation.** `optimal_width` is computed from the widest CL row and the widest banner; a spacer with empty
  `Text("")` does not affect either. No change.

## Test plan

1. **Unit / layout tests.** There is an existing `tests/ace/tui/models/test_changespec_groups_layout.py` that covers
   `build_changespec_tree` shape. The spacer is a _render_-layer concern, not a tree-layer concern, so that file does
   not need changes. Look for a render-layer test (likely under `tests/ace/tui/widgets/`) — if one exists, add a case
   asserting that two consecutive L0 banners produce a disabled empty option between them, and that L1 sub-banners do
   not get a leading spacer. If no such test exists, this is a small enough visual change that we can rely on the
   agents-tab analogue's existing coverage and verify by hand.
2. **Manual smoke test.** Open `sase ace`, switch to the CLs tab, set `BY_STATUS` grouping (the case with the most L0
   groups in the common workflow), and confirm:
   - There is a blank row between each pair of adjacent L0 banners.
   - There is **no** blank row above the first L0 banner.
   - There is **no** blank row between an L0 banner and its immediately-following L1 sibling-root sub-banner.
   - Up/Down arrow navigation skips the spacer rows (they are `disabled`).
   - Jump-hint letters on banners still resolve correctly.
   - Repeat for `BY_PROJECT` (also has L1 sibling-root level) and `BY_DATE` (no L1 level).
3. **`just check`** before reporting done.

## Out of scope

- Changing the _amount_ of vertical space (one blank row only — same as agents tab).
- Adding spacing between L0 and L1 banners, or between L1 banners.
- Any banner styling or color changes.
- Any change to the agents-tab spacer logic.

## Files touched

- `src/sase/ace/tui/widgets/_changespec_list_render.py` — add `Text` import, add spacer-emission block in
  `render_grouped()`.

That's the entire scope.
