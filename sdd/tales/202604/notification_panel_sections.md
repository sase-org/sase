---
create_time: 2026-04-25 23:24:32
status: done
prompt: sdd/prompts/202604/notification_panel_sections.md
---
# Sectioned Notification Panel

## Problem

The notification modal (`src/sase/ace/tui/modals/notification_modal.py`) renders every unread notification as a flat
`OptionList`. Visually, the only distinction between rows is a per-row prefix: `*` for unread, `~` for muted, dimmed
text for muted bodies. With even a modest backlog this turns into wallpaper — it's hard to spot the one plan-approval
row sitting between five sync notices and four muted error digests.

Now that we have a clean `is_priority()` classifier (added in commit `3a813e8d` for the indicator work), we can surface
that same signal _inside_ the modal: priority items pop into their own section at the top, ordinary unread items sit in
a middle "Inbox" section, and muted items get their own quieted section at the bottom. The user shouldn't have to scan
or sort to find the action-required notifications.

## Goals

1. **Three sections, in fixed order**: PRIORITY → INBOX → MUTED.
2. **Section headers are visually obvious** — a colored accent bar, a label, and a per-section count, color-keyed to
   match the indicator (red / gold / dim-cyan).
3. **Empty sections are hidden** so the panel never shows a "PRIORITY (0)" header.
4. **Keyboard navigation flows naturally** across sections — j/k/arrow keys move row-to-row, skipping headers.
5. **Section headers are not selectable / not actionable** — Enter, x, m, s, e all no-op when a header is highlighted.
6. **Existing behaviors preserved**: mute, snooze, dismiss, read-all, file-pane sync, plan/question confirmation flow,
   `initial_index`, the `q`/close binding, the bottom hint line.

## Non-goals

- No changes to the notification storage model, sender APIs, or `is_priority()` itself.
- No changes to per-notification row rendering (`_create_styled_label`) — the prefix/dim/badge styling stays identical.
- No changes to the indicator widget or to toast routing.
- No introduction of a fourth "Snoozed" section. Snoozed notifications imply muted (the modal already enforces this in
  `action_snooze`), so they sit inside MUTED with their existing inline `· in 1h30m` badge as the differentiator.

## Section taxonomy

Sections are pure functions of the existing `Notification` fields plus `is_priority()`:

| Section      | Predicate                                            |
| ------------ | ---------------------------------------------------- |
| **PRIORITY** | `not n.muted` and `is_priority(n)`                   |
| **INBOX**    | `not n.muted` and `not is_priority(n)`               |
| **MUTED**    | `n.muted` (regardless of priority — muted dominates) |

A muted priority notification lives in MUTED, not PRIORITY. The user has explicitly silenced it; respecting that mute is
more important than re-elevating it because of its type.

## Visual design

### Section headers

Each header is a single row rendered like this (60-col illustration; actual width tracks the option-list column):

```
▌ PRIORITY · 2 ─────────────────────────────────────────────
* [axe] 12 errors in build              10m  [error] 2 files
* [crs] CRS workflow failed              2m  [error]
▌ INBOX · 3 ────────────────────────────────────────────────
* [user-agent] sync complete             1m   [agent]
* [hitl] approve patch                   8m   [HITL]
* [user-workflow] daily digest          25m
▌ MUTED · 4 ────────────────────────────────────────────────
~ [user-agent] noisy retry              45m   [agent]
~ [user-workflow] muted digest          1h    · in 1h30m
~ [test] muted on purpose               2h
~ [test] another muted                  3h
```

Components of each header:

- **Accent bar**: `▌` (U+258C, half-block) at the very start, color-keyed per section.
- **Label**: uppercase section name (`PRIORITY`, `INBOX`, `MUTED`).
- **Count**: ` · N` immediately after the label — same `·` glyph the indicator already uses.
- **Trailing rule**: a row of `─` (U+2500) padding to the option-list width, dimmed. This gives the header a
  poster-style feel and makes the section break unmistakable on a 256-color terminal.

Why the trailing rule rather than a right-aligned count: right-aligning inside an `OptionList` row is unreliable
(content width is variable, scrollbars eat columns); the rule gracefully truncates if the column is narrow, and the
count stays anchored to the label where the eye lands first.

### Color palette

Aligned with the indicator colors picked in the prior plan, so headers, badge color, and counts read as one system:

| Section  | Header style                                    |
| -------- | ----------------------------------------------- |
| PRIORITY | `bold #FF4444` for `▌`, label, count            |
| INBOX    | `bold #FFD700` for `▌`, label, count            |
| MUTED    | `bold #5FAFAF` for `▌`, label, count (dim cyan) |

The trailing `─` rule is `dim` for all three sections so the section divider feels structural, not decorative.

### Row spacing

No blank-line padding above or below headers. The accent bar + rule already create a clear visual break, and adding
empty rows would waste vertical space in a modal that's already tight when the backlog is large.

### Empty modal

Unchanged: the "No unread notifications" centered Static stays exactly as it is today. No headers render in the empty
state.

## Interaction design

### Navigation

- `j` / `k` / arrow keys: row-to-row, **skipping headers** automatically. If the user lands on a header row (via mouse
  click, initial mount, or post-rebuild restore), the modal advances the highlight to the next selectable row in the
  same direction of travel; if there is none, it falls back to the previous direction.
- `g` / `G` (already provided by `OptionListNavigationMixin`): jump to first / last selectable row, again skipping
  headers.
- `<ctrl+n>` / `<ctrl+p>` continue to mean next/previous attached **file** for the highlighted notification (unchanged).

### Header non-selectability

Headers are added to the option list as `Option` instances with `id="hdr:priority"`, `id="hdr:inbox"`, `id="hdr:muted"`
(string-prefixed so they never collide with notification indices, which are numeric strings). Selection / action
handlers all guard against header ids:

- `on_option_list_option_selected`: ignore if `option.id` starts with `hdr:`.
- `on_option_list_option_highlighted`: if header, advance to next/previous selectable row.
- `_get_selected_index()`: return `None` if the highlighted option is a header.
- All actions (`x`, `y`, `n`, `m`, `s`, `e`, `R`, file scroll) early-return on `None` — already the existing pattern, so
  most just keep working.

### Mute / unmute / snooze and section migration

Today, mute just toggles a flag and rebuilds. With sections, the action causes the row to migrate:

- **Mute** an INBOX or PRIORITY row → it moves into MUTED.
- **Unmute** a MUTED row → it moves into PRIORITY (if priority-typed) or INBOX.
- **Snooze** an INBOX or PRIORITY row → snooze sets muted, so it moves into MUTED.

Highlight policy after the move: **follow the moved notification to its new section.** Rationale:

- Lets the user quickly undo (unmute / un-snooze) if they mis-tapped.
- Matches today's `_rebuild_list(highlight_index=idx)` behavior, which already keeps the highlight on the same
  notification.
- The alternative ("stay in source section, advance to next row") feels good for streak-muting but breaks undo
  ergonomics. We can revisit if real usage suggests otherwise.

### Dismiss

Unchanged. Dismissed notifications are removed from `self._notifications` entirely; the rebuild reflows the remaining
sections; highlight policy = "next item in former section, falling back to previous, falling back to first selectable
row" (today's behavior, generalized for sections).

### Read-all (`R`)

Marks all as read but does **not** mute. So PRIORITY/INBOX rows stay in their sections; only their `*` prefix
disappears. MUTED stays MUTED. No section migration. (The current code already only sets `read=True`.)

## Implementation plan

### Files to change

1. **`src/sase/ace/tui/modals/notification_modal.py`** — bulk of the change. Specifically:
   - Add a private `_SECTIONS` table mapping section key → (label, color, predicate).
   - Replace `_create_options()` with `_create_sectioned_options()` that returns an ordered list mixing header `Option`s
     (id=`hdr:<key>`) and notification `Option`s (id=str(notification_index)) — headers only emitted for non-empty
     sections.
   - Add `_section_for(notification)` returning `"priority" | "inbox" | "muted"`.
   - Add `_build_header_text(key, count)` returning the styled `Text` (accent bar + label + count + dim rule).
   - Update `_get_selected_index()` to ignore `hdr:` ids.
   - Update `on_option_list_option_highlighted` and `on_option_list_option_selected` to skip / no-op on header ids.
     Highlight skip uses `option_list.action_cursor_down()` / `_up()` based on previous highlight position.
   - Update `_rebuild_list(highlight_index=...)` so `highlight_index` continues to mean "notification index in
     `self._notifications`" but is translated to the row position in the freshly-built option list before assigning to
     `option_list.highlighted`. Add a small helper `_row_for_notification_index(idx) -> int | None`.
   - Update `on_mount` to translate `self._initial_index` (a notification index) the same way.

2. **`src/sase/ace/tui/styles.tcss`** — no structural changes, but a small touch-up:
   - Slightly tighten `#notification-list` padding if the headers feel cramped against the border (will eyeball during
     manual testing; if no change is needed, this file is untouched).

3. **`src/sase/notifications/priority.py`** — no change. Public surface (`is_priority`) stays as-is.

4. **`src/sase/notifications/__init__.py`** — no change (already exports `is_priority`).

### Files NOT to change

- `src/sase/notifications/store.py`, `models.py`, `senders.py` — no schema changes.
- `src/sase/ace/tui/widgets/notification_indicator.py` — independent.
- `src/sase/ace/tui/actions/agents/_notifications.py`, `_toasts.py`, `lifecycle.py` — independent.
- All other modals.

### Tests

Update **`tests/test_notification_modal.py`** with a new section-rendering block:

- `test_sections_render_in_priority_inbox_muted_order`: build a modal with one of each, assert option ids appear in the
  order `hdr:priority`, `<priority idx>`, `hdr:inbox`, `<inbox idx>`, `hdr:muted`, `<muted idx>`.
- `test_empty_section_header_not_rendered`: build with only inbox notifications; assert no `hdr:priority` and no
  `hdr:muted` options.
- `test_header_is_non_selectable`: simulate `_get_selected_index` when highlighted is a header → returns `None`. Verify
  `action_dismiss_notification` and `action_toggle_mute` no-op when index is None.
- `test_muted_priority_lives_in_muted_section`: a priority-typed but muted notification is placed under MUTED, not
  PRIORITY.
- `test_mute_migrates_into_muted_section`: mute an inbox row, rebuild, highlighted option is now under the MUTED header
  and points at the same notification id.
- `test_initial_index_resolves_to_correct_row`: open with `initial_index=2` where notification 2 is the muted row;
  assert the option list highlight lands on the correct option position (post-header-offset).

Existing tests (`test_dismiss_notification_*`, `test_toggle_mute_*`, `test_snooze_*`, `test_read_all_*`) should keep
passing without behavioral changes — only the option-list's row count and highlight indices shift.

The `OptionListNavigationMixin` "skip header on highlight" behavior is best verified manually in the TUI, since
simulating `OptionList.action_cursor_down()` cleanly in a unit test requires a Textual `App.run_test()` harness; if the
existing test suite already uses one for this modal we'll add a small flow test, otherwise we document the manual check
in the PR description.

## Risks & open questions

- **Header glyph fallback**: `▌` and `─` are widely supported but not universal. If a user's terminal renders them as
  tofu, the section break will look ugly. Mitigation: stick with characters already used elsewhere in the TUI (the
  indicator and ChangeSpec widgets already lean on Unicode block chars and box-drawing, so we're consistent with the
  rest of the app). No fallback path planned.
- **Cursor-skip robustness**: skipping headers on highlight depends on knowing the direction of cursor travel. Textual
  `OptionList.OptionHighlighted` doesn't expose direction; we'll infer it by comparing the new highlight position to the
  previous one cached on the modal instance. Edge case: when the previous position equals the new position (no cached
  prior), default to "advance downward". Should be invisible in practice.
- **Order stability**: today, `self._notifications` is rendered in the order it was passed in (caller-determined,
  usually newest-first). With sections, the in-section order remains caller order — we don't re-sort within a section.
  Worth confirming that's the user's expectation (no recency mixing inside sections).
- **Mute-then-undo highlight flicker**: following the muted notification across a section boundary will visibly jump the
  highlight to a different row of the screen. This is the same as today's "rebuild keeps highlight on same id" behavior,
  just more noticeable now. If it's distracting we can switch to "stay in source section" — easy follow-up.
- **Help modal**: the `?` help popup currently doesn't document modal-internal section semantics. I'll add a one-line
  description of the sections to the modal-specific section of the help, matching the indicator help line added in the
  prior PR.
