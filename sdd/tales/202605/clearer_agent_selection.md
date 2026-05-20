---
create_time: 2026-05-20 18:31:32
status: done
prompt: sdd/prompts/202605/clearer_agent_selection.md
---
# Plan: Clearer Selected Agent Entry on the `sase ace` Agents Tab

## Problem

On the `sase ace` TUI's "Agents" tab, the currently selected agent row is hard to pick out at a glance. The current
selection styling is a subtle 25% accent tint plus a thick left border plus bold text. With colored row content (status
badges, teal agent names, tier gutter glyphs, tag chips, etc.), the tinted background does not pop enough — the eye has
to hunt for the highlighted row.

The user wants a **clearer** selection indicator that still looks **beautiful**, without changing any of the row's
syntax-highlighting colors (agent name color, status colors, tier gutter colors, tag colors, query token colors in the
info panel, etc.).

## Goals & Non-Goals

### Goals

1. The selected agent row should be **immediately** identifiable, even when scanning a screen full of colorful status
   badges.
2. The visual treatment should feel intentional and refined — consistent with the existing accent-based palette, not a
   loud new color.
3. The change should be local and low-risk: no new render-time branches in the per-row formatter, no cache invalidation
   churn.

### Non-Goals (explicit guardrails)

- **No changes to row content syntax highlighting.** All inline Rich markup colors stay exactly as they are:
  - Agent name (`#00D7AF`, bold when selected)
  - All status colors (DONE green, FAILED red, RUNNING gold, WAITING amethyst, QUESTION amber, PLAN pink/teal, etc.)
  - Tier gutter guide colors
  - Tag chips (`#FFD75F`), marked checkmark (`#00D700`), retry glyph (`#FFAF00`), bead glyph (`#5FD7AF`), runtime suffix
    tokens
  - The agent-query token palette in `AgentInfoPanel` (`#87AFFF` keyword, `#FF5F5F` negation, etc.)
- No changes to banner rows (project/ChangeSpec/bucket headers are `disabled` and don't take the cursor).
- No new selection-marker glyph in row content. Prepending a `❯` caret would require editing the cached row formatter
  and would risk misaligning tier gutters and child-indent — out of scope. TCSS-only.
- No change to the agent info panel above the list.

## Design

Today's rule (`src/sase/ace/tui/styles.tcss` lines 992–997):

```tcss
AgentList > .option-list--option-highlighted {
    background: $accent 25%;
    text-style: bold;
    border-left: thick $accent;
    padding: 0 1 0 0;
}
```

The ingredients are right — tinted background, accent left bar, bold — they just don't have enough presence. The
proposed design strengthens the same three ingredients into a coherent "highlighted card" effect:

```tcss
AgentList > .option-list--option-highlighted {
    background: $accent 40%;
    text-style: bold;
    border-left: thick $accent;
    padding: 0 1 0 0;
}
```

### What changes, and why each beat is deliberate

1. **Background bumped from `$accent 25%` → `$accent 40%`.** This is the primary readability win. At 25%, the tint reads
   as "this row is slightly different"; at 40%, it reads as "this row is selected." 40% is still translucent enough that
   the bright row content (teal name, gold/green status, etc.) stays readable on top — we don't approach the saturation
   level where foreground colors get washed out.

2. **Thick accent left border kept.** This is the "anchor" of the selection cue: a full-opacity vertical accent bar
   against the 40% tinted fill creates a small but pleasing two-tone edge — like the leading bar of a Markdown
   blockquote. The border at full opacity against the now-stronger fill produces a clearer "lifted card" feel than 25%
   fill + same border did.

3. **Bold kept.** Already part of the existing rule; combined with the inline `bold #00D7AF` on the agent name in the
   renderer, the selected row's text weight visibly outranks neighboring rows.

4. **Padding asymmetry kept (`0 1 0 0`).** This compensates for the `thick` left border so row content does not shift
   horizontally between selected and unselected states. Leaving this alone prevents alignment jitter as the cursor
   moves.

### Design alternatives considered (and rejected)

- **Reverse video (`text-style: bold reverse`).** Would invert the row's syntax-highlighted colors. Rejected — that's
  exactly the syntax-highlighting change the user told us not to make.
- **`outer` / all-around border.** Would add a thin frame on top and bottom of the selected row. Rejected — visually
  noisy at row-height 1, would collide with adjacent rows, and worsens vertical density.
- **Add a right-edge accent bar.** Rejected — `OptionList` rows live inside a scroll container with
  `scrollbar-gutter: stable`. A right border risks overlap/jitter with the scrollbar gutter.
- **Add a `❯` selection caret in row content.** Rejected — would require editing `_agent_list_render_agent.py` (the
  syntax-highlighting render layer), threading `is_selected` through more places, and re-tuning tier gutter / child
  indent column alignment. Higher risk for a marginal gain given the TCSS change alone solves the readability complaint.
- **Brighter named color instead of `$accent`.** Rejected — `$accent` is the theme variable; using it keeps the
  selection in lockstep with whatever theme is active and with the rest of the TUI's accent usage.

## Implementation

### File changes

- **`src/sase/ace/tui/styles.tcss`** — single edit, lines 992–997: change `background: $accent 25%;` to
  `background: $accent 40%;`. No other rules touched.

That is the entirety of the production code change.

### Verification

- **Visual sanity check**: run the TUI (`sase ace`), open the Agents tab, move the cursor with `j`/`k`, and confirm the
  selected row visibly "lifts" while neighboring rows remain calm. Verify the selected row's inline colors (agent name,
  status badge, tier gutter glyphs, tags) all render identically to before — only the row background and edge feel
  stronger.
- **Theme check**: cycle themes (if the harness supports it) to make sure the `$accent 40%` reads well in both light and
  dark themes.
- **Status mix check**: with the test fixture containing a variety of statuses (RUNNING gold, FAILED red, DONE green,
  WAITING amethyst), verify none of those colors look washed-out against the 40% accent fill on the selected row.

### PNG snapshot updates

The exploration agent identified three PNG goldens that may need regeneration:

- `tests/ace/tui/visual/snapshots/png/agents_selected_row_120x40.png` (`test_agents_selected_row_png_snapshot`) —
  directly captures a moved cursor on the Agents tab; **will need refresh**.
- `tests/ace/tui/visual/snapshots/png/agents_list_120x40.png` (`test_agent_list_png_snapshot`) — initial Agents view;
  **likely needs refresh** because OptionList highlights the first row on focus.
- `tests/ace/tui/visual/snapshots/png/agents_unread_highlight_120x40.png` (`test_agents_unread_highlight_png_snapshot`)
  — captures unread state; **may need refresh** if the cursor row coincides with the unread display.

Workflow: run `just test-visual`, inspect diffs in `.pytest_cache/sase-visual/` (actual vs expected vs diff vs source),
and once visually confirmed correct, accept with `just test-visual --sase-update-visual-snapshots` (or the equivalent
`pytest --sase-update-visual-snapshots` invocation).

### Final checks

- `just check` before reporting back to the user — required by repo conventions any time files in this repo change.

## Risk

Very low. The change is one CSS property value bump within an already-active selector. It does not touch row formatting
code, the render cache, the agent-query highlighter, or any test other than PNG goldens that exist explicitly to track
the selection's visual presentation. If the new fill opacity reads wrong in some theme we don't have a snapshot for, the
rollback is a one-character edit.
