---
create_time: 2026-05-11 15:25:37
status: done
prompt: sdd/prompts/202605/highlight_unread_agent_count.md
---
# Highlight the Agents-tab Unread Count with a Yellow Background

## Goal

Make the unread-completed-agent count number in the Agents-tab info-panel header pop visually, so that users can still
see "you have unread completed agents" at a glance now that the **sase-2v** epic has bulk-dismissed the per-agent
`JumpToAgent` notifications on tab arrival / activity.

Concrete change: render the unread count digits in the metric strip with a **yellow background and black foreground**
(plus existing bold) instead of the current bold-amber foreground on the default panel background.

The label (` unread`) and the surrounding `[ … · … ]` separators stay dim — only the numeric value changes — keeping the
rest of the header visually consistent with the other metric counts.

## Why This Change Now

The sase-2v epic (commits b9f525a0 → fcb2c1bc) intentionally severed the link between unread agent rows and the
`JumpToAgent` notification badge in the top-right `NotificationIndicator`:

- **Before sase-2v:** every completed-but-unseen agent emitted a `JumpToAgent` notification, which loudly counted up in
  the orange/gold `NotificationIndicator`. The user had a hard-to-ignore badge that screamed at them.
- **After sase-2v:** simply arriving at the Agents tab (or pressing `j`/`k` on it) bulk-dismisses every outstanding
  `JumpToAgent` notification. The notification badge clears, but `_unread_completed_agent_ids` (and therefore the
  Agents-tab info-panel "N unread" count) remains intact — that was an explicit decision so manually-unread rows still
  read as "starred for follow-up" (see plan §"Manual unread rows stay unread").

The side effect is that the only surviving "you still have unseen completed work" signal is the modest `bold #FFAF5F` "N
unread" number inside the Agents tab header. On a colorful header strip (teal `running`, amethyst `waiting`, red
`failed`, cyan `read`), that amber number is easy to gloss over — exactly the regression we need to compensate for.

A yellow-on-black highlight pulls the number into the same visual register as the previous orange/gold notification
badge, restoring "this is the count that matters" emphasis without bringing back the per-row notification dismissal
friction that sase-2v removed.

## Current State

`src/sase/ace/tui/widgets/agent_info_panel.py` defines a `_COUNT_STYLES` dict (added by the
`sdd/tales/202605/agent_header_number_colors.md` change). The unread entry is:

```python
_COUNT_STYLES: dict[str, str] = {
    "asking": "bold #FFAF00",
    "running": "bold #00D7AF",
    "waiting": "bold #AF87FF",
    "failed": "bold #FF5F5F",
    "unread": "bold #FFAF5F",   # <-- target of this change
    "read": "bold #5FD7FF",
}
```

`_append_metric_strip()` renders each number with `style=self._COUNT_STYLES[label]` and the suffix label with
`style="dim"`. Rich's `Text.append(...)` supports background colors via the `on <color>` form (already used by
`NotificationIndicator`: `"bold #1a1a1a on #FFD700"`), so changing this is purely a style-string swap — no widget
plumbing or call-site changes.

`tests/ace/tui/widgets/test_agent_info_panel.py::test_agent_count_numbers_have_rich_styles` pins the current style
strings exactly, and `test_update_agent_counts_uses_plain_metric_text` asserts the literal substring `"#FFAF5F"` is
**not** in the plain-text output (which remains true after the swap — it only inspects `.plain`, not styles).

The two visual snapshots that might include the metric strip are:

- `tests/ace/tui/visual/snapshots/png/agents_list_120x40.png`
- `tests/ace/tui/visual/snapshots/png/agents_selected_row_120x40.png`

The fixture seeding behind those snapshots determines whether the unread count is non-zero (and therefore whether the
pixel diff actually changes). The plan accounts for refreshing them if so.

## Design

### Color choice

- **Background:** `#FFD700` — the same saturated gold the `NotificationIndicator` uses for unmuted non-priority
  notifications. Reusing it makes the unread highlight feel like a reincarnation of the badge the user used to see in
  the top-right corner, which is exactly the visual continuity we want post-sase-2v.
- **Foreground:** `#1a1a1a` — near-black, matching the foreground `NotificationIndicator` already pairs with `#FFD700`
  for readable contrast. Pure `black` is also fine; reusing `#1a1a1a` keeps the two highlights pixel-consistent.
- **Weight:** keep `bold` to maintain weight parity with the other count styles.

Final Rich style string: `"bold #1a1a1a on #FFD700"`.

### Where the change happens

Single-line edit in `_COUNT_STYLES` inside `src/sase/ace/tui/widgets/agent_info_panel.py`:

```python
"unread": "bold #1a1a1a on #FFD700",
```

No structural / formatting changes to the metric strip:

- Label (` unread`) stays `dim`.
- Separators (`·`) stay `dim`.
- All other count entries (asking / running / waiting / failed / read) are untouched.
- Loading state (`Agents: …`) is unchanged — there are no count numbers visible while loading.

### Scope discipline

This change is **presentation-only**, targeted at the _unread_ count in the Agents-tab info-panel header. It does
**not**:

- Touch the per-row "unread completed" rendering in `_agent_list_render_layout.py` (`🎉` marker / `#FFD75F`). The marker
  is already prominent and lives in the row, not the header.
- Touch the `NotificationIndicator` widget.
- Re-introduce any of the sase-2t / sase-2u reverted code paths (per-tab unread badge on the TabBar, suppression
  filters, etc.) — those were rolled back deliberately, and this header-highlight is a minimal compensating tweak that
  stays inside the surviving widget.
- Change the count computation in `AgentDisplayMixin._update_agents_info_panel()` or the underlying
  `_unread_completed_agent_count` helper.

## Implementation Steps

1. **Edit `src/sase/ace/tui/widgets/agent_info_panel.py`**: change the `"unread"` entry of `_COUNT_STYLES` to
   `"bold #1a1a1a on #FFD700"`.
2. **Update `tests/ace/tui/widgets/test_agent_info_panel.py::test_agent_count_numbers_have_rich_styles`**: change the
   pinned style for the `"unread"` key from `"bold #FFAF5F"` to `"bold #1a1a1a on #FFD700"`. Leave every other pinned
   style as-is.
3. **Sanity-check the substring assertion** in `test_update_agent_counts_uses_plain_metric_text`: it asserts
   `"#FFAF5F" not in plain`, which still holds (the assertion inspects `.plain`, which contains no style hex strings).
   No change required; the test will continue to pass.
4. **Refresh visual snapshots if needed.** Run `just test` (which executes the PNG visual snapshot suite). If
   `agents_list_120x40.png` or `agents_selected_row_120x40.png` regress on the unread number pixels, re-record them
   following the existing fixture-update workflow used by sase-2v.4 / earlier visual regressions. Verify the only diff
   is in the header `N unread` glyph block; abort and investigate anything else.
5. **Run `just check`** before declaring the task complete, per the repo-wide instruction in
   `memory/short/build_and_run.md`. (Run `just install` first if the workspace is stale.)

## Edge Cases & Decisions

1. **Zero-unread case.** `_append_metric_strip` already filters zero-valued metrics, so a row of `0 unread` never
   renders. The yellow highlight is only visible when there is something to look at — which is exactly the desired "this
   matters when it appears" UX. No special-casing required.
2. **Other tabs.** `AgentInfoPanel` is the Agents tab's header widget. The highlight does not leak to ChangeSpec, Axe,
   or other tabs.
3. **Terminal background colors.** `#FFD700` + `#1a1a1a` is the same pairing already battle-tested by
   `NotificationIndicator` across both dark and light terminals, so we inherit that contrast posture rather than
   inventing a new one.
4. **Visual snapshot fixture has zero unread.** If the existing snapshot fixtures happen to seed `_unread_count = 0`,
   the snapshots will not change pixel-for-pixel; this is fine and means step 4 is a no-op. Verify by running the visual
   suite once before deciding the snapshots need a refresh.
5. **Future re-styling.** This is the same line that previous tales (`agent_header_number_colors.md`,
   `read_agent_count_color.md`, `agent_total_neutral_style.md`) have been iterating on. Keep the new style string in the
   same `_COUNT_STYLES` dict — do not break the convention by hoisting it out or coupling it to per-row marker styles.

## Out of Scope

- Re-adding the per-tab unread badge on `TabBar` (sase-2u, reverted).
- Re-adding notification-suppression filters (sase-2t, reverted).
- Adjusting the _row-level_ "completed but unread" marker (`🎉` / `#FFD75F`) in the agent list — that already pops.
- Changing the `NotificationIndicator` widget.
- Any change to the `_unread_completed_agent_ids` state machine or the manual-unread guard.

## Test Plan

- **Unit (focused):**

  ```bash
  ./.venv/bin/python -m pytest tests/ace/tui/widgets/test_agent_info_panel.py tests/ace/tui/test_startup_loading_indicators.py
  ```

  Expect the updated style assertion to pass and the other panel-content tests (plain-text headers, loading state, group
  badge) to continue passing untouched.

- **Visual regression:**

  ```bash
  just test
  ```

  Inspect `agents_list_120x40.png` / `agents_selected_row_120x40.png` diffs. If unread is present in the fixture,
  confirm the pixel diff is localized to the `N unread` glyph block in the header and re-record the snapshot; if not, no
  snapshot updates needed.

- **Repo gate:**
  ```bash
  just check
  ```
  Required before reporting the task complete.

## Touched Files (estimated)

- `src/sase/ace/tui/widgets/agent_info_panel.py` — one-line style change in `_COUNT_STYLES`.
- `tests/ace/tui/widgets/test_agent_info_panel.py` — update pinned `"unread"` style in
  `test_agent_count_numbers_have_rich_styles`.
- (Conditionally) `tests/ace/tui/visual/snapshots/png/agents_list_120x40.png` and/or
  `tests/ace/tui/visual/snapshots/png/agents_selected_row_120x40.png` if the fixtures seed a non-zero unread count.
