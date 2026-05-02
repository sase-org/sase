---
create_time: 2026-04-25 23:39:41
status: done
prompt: sdd/prompts/202604/notification_panel_polish.md
---
# Notification Panel Polish

## Context

Four recent commits layered features onto the notification panel and its top-bar indicator:

- `63679dad` per-notification mute toggle (adds `~` prefix + dim row body)
- `3a813e8d` priority-aware indicator (red/gold/dim-cyan ✉ pill)
- `2f92b366` snooze (adds `· in {t}` trailing badge)
- `e449f633` PRIORITY/INBOX/MUTED section headers in the modal

The features are all in place and correct. This plan is opinionated visual polish — changes I would only make if they
are unambiguous wins. I am explicitly **not** proposing layout reshuffles, recoloring of the priority palette, or
bracket-style overhauls.

Files in scope:

- `src/sase/ace/tui/modals/notification_modal.py`
- `src/sase/ace/tui/widgets/notification_indicator.py`

No styles.tcss changes. No behavior changes. No new bindings or actions. Tests already cover indicator content and
section structure; we will update the affected assertions.

## Wins

### Win 1: stop printing `0+` in the indicator when there are no priority items

`NotificationIndicator._build_content` always renders `✉ {p}+{r}`, so a typical state of "5 unread, all inbox-class"
reads as `✉ 0+5`. The `0+` is pure noise — the gold color already tells the user "no priority, inbox only". When
`priority == 0`, render `✉ {rest}`. When only muted remain, render `✉ {muted}` (dim-cyan keeps the "acknowledged
backlog" signal). Keep the `+` form **only** when `priority > 0`, which is the case where the split actually carries
information.

Resulting matrix:

| state              | before      | after       |
| ------------------ | ----------- | ----------- |
| nothing unread     | `✉ 0` (dim) | `✉ 0` (dim) |
| 5 inbox            | `✉ 0+5`     | `✉ 5`       |
| 2 priority, 5 rest | `✉ 2+5`     | `✉ 2+5`     |
| 3 muted only       | `✉ 0+0 ·3`  | `✉ 3` cyan  |
| 5 inbox + 3 muted  | `✉ 0+5 ·3`  | `✉ 5 ·3`    |

All information is preserved; the only thing dropped is the `0+` literal when it carries no signal. The secondary
`·{muted}` segment is unchanged in form when both segments are present.

### Win 2: align the row prefix column

`_create_styled_label` emits `"~ "` for muted, `"* "` for unread, and nothing for read-and-unmuted rows. The `[sender]`
of a read row therefore starts two cells to the left of its neighbours, producing a ragged left edge whenever the
section mixes read and unread items (common in INBOX after partial dismissals). Always reserve the 2-cell prefix slot —
emit `"  "` (two spaces) when there is no glyph. Pure visual fix, no semantics changed.

### Win 3: drop the fixed-width trailing rule on section headers

`_build_header_text` appends `"─" * 40` after the header label. With the modal's left pane at 40% of a 95%-wide window,
the rule either wraps into a second line on narrow terminals or stops well short of the right edge on wide ones — it
never lines up. The bold colored bar, label, and count are already a strong section delimiter on their own. Drop the
trailing dashes. (The header row stays disabled and skipped by the cursor; only the trailing decoration goes.)

### Win 4: replace `· in 14m` with a clock glyph

The snooze badge currently reads `  · in 14m` and is rendered in the same dim style as the relative-time stamp two
columns to its left. The leading `·` is doing separator duty even though the surrounding `"  "` already separates
fields, and "in" is filler. A single clock glyph is self-documenting and visually distinct from the timestamp. Render
`⏰ 14m` (still dim — we are not un-muting the row, just making the most ephemeral data point on the row easier to
spot).

## Out of scope (deliberately)

- **Action badge bracket style.** `[CL]` vs `[mentor]` vs `[HITL]` mixes caps; rationalising it touches names users may
  have learned and is subjective. Skip.
- **Sender-vs-action visual distinction.** Both use `[…]` brackets, which is mildly ambiguous, but disambiguating
  cleanly (chevrons, parens, color coding) is a redesign, not a polish pass.
- **Hints line compaction.** It is long but readable, and shortening risks dropping discoverability of bindings users
  actually need.
- **CSS / layout / 40-60 split.** No structural changes.

## Implementation sketch

1. `notification_indicator.py::_build_content`
   - When `priority == 0 and rest > 0`: primary text `f" ✉ {rest} "`.
   - When `priority == 0 and rest == 0 and muted > 0`: primary text `f" ✉ {muted} "` in the existing dim-cyan style; do
     **not** also append `·{muted}` (it would duplicate the count).
   - Keep `f" ✉ {priority}+{rest} "` for the `priority > 0` branch.
   - Keep the `·{muted}` secondary segment when there is a primary count to differentiate from.

2. `notification_modal.py::_create_styled_label`
   - Always append a 2-cell prefix; use `"  "` (plain, no style) for the read-and-unmuted case.

3. `notification_modal.py::_build_header_text`
   - Drop the trailing `text.append(" ", style="")` and `text.append("─" * 40, style="dim")`.

4. `notification_modal.py::_create_styled_label` (snooze branch)
   - Replace `f"  · in {format_relative_until(...)}"` with `f"  ⏰ {format_relative_until(...)}"`. Keep dim style.

## Test impact

- `tests/ace/tui/widgets/test_notification_indicator*.py`: assertions on the `0+` literal need updating to the new
  format; add a case for the muted-only collapse.
- `tests/ace/tui/modals/test_notification_modal*.py`: any test that asserts on the `─` separator in header text or on
  the `· in` snooze text needs updating. Tests that count rows / check section ordering should pass unchanged.

## Validation

- `just check` (lint + mypy + tests).
- Manual TUI sanity: open the modal with a mix of read/unread, muted, and snoozed notifications; confirm prefix
  alignment, header lines end at the label, snooze rows show the clock glyph, and the top-bar indicator collapses the
  `0+` cases as described.
