---
status: proposed
create_time: 2026-05-11 15:46:25
prompt: sdd/prompts/202605/unread_label_highlight.md
---

# Extend Unread Highlight Across the Label Word

## Goal

In the Agents-tab info-panel header strip, render the **entire** unread token — the digit, the separating space, and the
literal word `unread` — with the yellow-on-black highlight (`bold #1a1a1a on #FFD700`). Today only the digit is
highlighted; the ` unread` suffix renders in `dim`, which makes the badge feel half-finished and dilutes the visual
weight we deliberately reintroduced after the sase-2v notification-badge severance.

After this change, the header reads (conceptually):

```
… [3 running · 1 failed · ▮3 unread▮ · 6 done]
```

where `▮…▮` denotes the yellow-on-black block — covering `3 unread` as one contiguous run. The opening `[`, the
surrounding `·` separators, the closing `]`, and every other count + label remain exactly as they are today.

## Why This Change Now

The previous tale (`sdd/tales/202605/highlight_unread_agent_count.md`) restored visual weight to the unread count by
giving the digit a yellow background. In practice, with realistic counts (single-digit `3`, `5`), one highlighted glyph
in a long strip still gets lost — the eye reads the dim ` unread` label as "another metric" and slides past the yellow
pixel. Extending the highlight across the full token (`3 unread`) gives the badge the same shape and rhythm as the old
`NotificationIndicator` chip, which is the visual register we are explicitly trying to revive post-sase-2v.

This is a tiny, presentation-only follow-up — the kind of pixel tuning that only becomes obvious once the first version
is in front of users.

## Current State

`src/sase/ace/tui/widgets/agent_info_panel.py`:

```python
_COUNT_STYLES: dict[str, str] = {
    "asking": "bold #FFAF00",
    "running": "bold #00D7AF",
    "waiting": "bold #AF87FF",
    "failed": "bold #FF5F5F",
    "unread": "bold #1a1a1a on #FFD700",
    "read": "bold #5FD7FF",
}

def _append_metric_strip(self, text: Text) -> None:
    metrics = [(label, count) for label, count in self._metric_counts() if count]
    if not metrics:
        return
    text.append(" [", style="dim")
    for index, (label, count) in enumerate(metrics):
        if index:
            text.append(" · ", style="dim")
        text.append(f"{count}", style=self._COUNT_STYLES[label])
        text.append(f" {self._COUNT_LABELS.get(label, label)}", style="dim")
    text.append("]", style="dim")
```

The `f" {self._COUNT_LABELS.get(label, label)}"` append is the single line that forces every label suffix to render
`dim`, regardless of which metric we are on.

### Tests that touch this code

- `tests/ace/tui/widgets/test_agent_info_panel.py::test_agent_count_numbers_have_rich_styles` pins the per-digit styles.
  Its assertions cover only the digit segments (`"64"` etc.), so the existing pinned style for the `unread` digit stays
  unchanged — the new behavior is additive on the label, not a redefinition of the digit.
- The other tests in the same file inspect `.plain` text only; they continue passing unchanged.

### PNG snapshot

`tests/ace/tui/visual/snapshots/png/agents_unread_highlight_120x40.png` was recorded with the digit-only highlight.
Extending the highlight onto the ` unread` glyphs changes those pixels, so this snapshot must be re-recorded via
`--sase-update-visual-snapshots`. No other PNG snapshot in the suite seeds a non-zero unread count, so this is the only
golden affected.

## Design

### Color

Reuse the existing `"bold #1a1a1a on #FFD700"` — the same string already pinned for the unread digit and for the
`NotificationIndicator` chip. No new color constant, no new dict entry hoisted out of `_COUNT_STYLES`. The point of this
tale is _spatial extent_, not palette tweaks.

### Shape of the highlighted run

The highlighted run is exactly `f"{count} {label_text}"` — i.e. the digit, one space, and the suffix word. We do **not**
extend the highlight across:

- the leading `" [`" — that opening bracket stays dim,
- the inter-metric `" · "` separators — they stay dim on both sides of unread,
- the trailing `"]"` — also dim.

That means the yellow block has clean dim borders on the left (`·` if unread isn't first, or `[` if it is) and on the
right (`·` if unread isn't last, or `]`). Since unread sits between `failed` and `read` in `_metric_counts()`, the
realistic neighbors are always the `·` separators, which keeps the badge visually isolated.

### Minimal code change

In `_append_metric_strip`, vary the label-suffix style by `label`. The unread label uses the same highlight as its
digit; every other label stays `dim`:

```python
def _append_metric_strip(self, text: Text) -> None:
    metrics = [(label, count) for label, count in self._metric_counts() if count]
    if not metrics:
        return
    text.append(" [", style="dim")
    for index, (label, count) in enumerate(metrics):
        if index:
            text.append(" · ", style="dim")
        count_style = self._COUNT_STYLES[label]
        text.append(f"{count}", style=count_style)
        suffix = f" {self._COUNT_LABELS.get(label, label)}"
        # Unread is the only metric whose label is part of the highlight.
        label_style = count_style if label == "unread" else "dim"
        text.append(suffix, style=label_style)
    text.append("]", style="dim")
```

Notes on the conditional:

- We branch on the literal string `"unread"` rather than introducing a new `_COUNT_LABEL_STYLES` dict. The existing
  `_COUNT_STYLES` / `_COUNT_LABELS` convention already keys by the same set of label strings; adding a third parallel
  dict for one entry would be more ceremony than the change merits.
- The space character between the digit and the word lives inside the highlighted run, so the yellow block reads as a
  single chip rather than as two adjacent rectangles separated by a dim gap. This is the user-visible point of the
  change.
- Bold is preserved on the label because the full Rich style string includes `bold`. No additional `bold` annotation is
  needed.

### Why not move `unread` to a separate dict / type?

The four prior tales that iterate on `_COUNT_STYLES` (referenced in `highlight_unread_agent_count.md`) deliberately keep
the data shape flat. Hoisting `unread` into its own structure now would break that convention for a one-line behavioral
difference. Keep the dict flat; encode the label-highlight rule as a one-line `if`.

## Test Plan

### Unit

Add one new test and extend one existing test in `tests/ace/tui/widgets/test_agent_info_panel.py`:

1. **Extend `test_agent_count_numbers_have_rich_styles`** to also assert the label segment styles, by adding a second
   mapping of expected label-suffix styles:

   ```python
   label_styles = {
       " stopped": _style_for_plain_segment(text, " stopped"),
       " running": _style_for_plain_segment(text, " running"),
       " waiting": _style_for_plain_segment(text, " waiting"),
       " failed": _style_for_plain_segment(text, " failed"),
       " unread": _style_for_plain_segment(text, " unread"),
       " done": _style_for_plain_segment(text, " done"),
   }
   assert label_styles == {
       " stopped": "dim",
       " running": "dim",
       " waiting": "dim",
       " failed": "dim",
       " unread": "bold #1a1a1a on #FFD700",
       " done": "dim",
   }
   ```

   This pins both directions: only the unread label is highlighted, and every other label remains dim. (Note:
   `_style_for_plain_segment` already exists in the test module — no helper changes needed.)

2. **Sanity-keep** the existing `test_update_agent_counts_uses_plain_metric_text` plain-text assertion — it does not
   inspect styles, so it continues to pass unchanged.

3. Run the focused suites:

   ```bash
   ./.venv/bin/python -m pytest \
     tests/ace/tui/widgets/test_agent_info_panel.py \
     tests/ace/tui/test_startup_loading_indicators.py
   ```

### Visual

Re-record the single affected PNG:

```bash
./.venv/bin/python -m pytest \
  tests/ace/tui/visual/test_ace_png_snapshots.py::test_agents_unread_highlight_png_snapshot \
  --sase-update-visual-snapshots
```

Then verify it locks in:

```bash
just test
```

Inspect the regenerated `tests/ace/tui/visual/snapshots/png/agents_unread_highlight_120x40.png` — confirm that the
yellow block now covers the `3 unread` glyph run and that no other pixels changed (the `running`, `failed`, and `done`
labels must remain visually dim).

### Repo gate

```bash
just check
```

Required before declaring done, per `memory/short/build_and_run.md`.

## Edge Cases & Decisions

1. **Zero-unread case.** `_append_metric_strip` filters zero metrics, so the highlight is never rendered when there is
   nothing to look at. Same posture as the prior tale.
2. **Unread is first / unread is last in the strip.** Order is fixed by `_metric_counts()` — unread is the fifth of six
   entries — so neighbors are deterministic (`failed` on the left, `read` on the right when both are non-zero). Even if
   both neighbors are zero, the dim `[` / `]` brackets bound the highlight cleanly. No special-casing.
3. **Leading space inside the highlight.** Yes — the single space between the digit and the word is part of the
   highlighted span. This is intentional: it makes the chip visually contiguous. The alternative (highlight digit, dim
   space, highlight word) produces a visible dim gap that defeats the purpose.
4. **Separator spacing.** The `·` between metrics is unchanged dim text; it is appended outside the per-metric loop body
   that handles the highlight, so there is no risk of accidentally inheriting the highlight style.
5. **Loading state.** `_update_display()` short-circuits to `Agents: …` before `_append_metric_strip` runs, so the
   highlight never renders mid-load.
6. **Future re-styling.** If a future tale needs to highlight a _second_ label (e.g. `failed`), the one-line
   `if label == "unread"` becomes a small set membership check or a dedicated dict. Defer that until the second case
   actually shows up.

## Out of Scope

- Touching any other metric label (`stopped`, `running`, `waiting`, `failed`, `done`).
- Restyling the surrounding brackets, separators, or the count-strip layout.
- Changing per-row "completed but unread" rendering in the agent list.
- Changing `NotificationIndicator`, `_unread_completed_agent_ids`, or the count computation in
  `AgentDisplayMixin._update_agents_info_panel`.
- Re-introducing any sase-2t / sase-2u code paths.

## Touched Files

- `src/sase/ace/tui/widgets/agent_info_panel.py` — extend `_append_metric_strip` to apply the highlight style to the
  unread label suffix (the one-line conditional shown above).
- `tests/ace/tui/widgets/test_agent_info_panel.py` — extend `test_agent_count_numbers_have_rich_styles` with
  label-suffix style assertions for all six labels.
- `tests/ace/tui/visual/snapshots/png/agents_unread_highlight_120x40.png` — regenerate via
  `--sase-update-visual-snapshots`; expect pixel diff only on the ` unread` glyphs.
