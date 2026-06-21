---
create_time: 2026-06-21 08:53:04
status: done
prompt: sdd/prompts/202606/agent_restore_panel_polish.md
---
# Polish the Agent Restore panel's left-pane group list

## Context

The "Agent Restore" modal (`SavedAgentGroupRevivalModal`) is a two-pane modal: a left pane that lists selectable
group/action rows in an `OptionList`, and a right pane that previews the highlighted group. This plan only touches the
**left pane** (the list of selectable entries) and its supporting row-rendering helper. The preview pane keeps all of
its richer detail, so nothing we trim from a row is actually lost — it remains visible in the preview.

Relevant files:

- `src/sase/ace/tui/modals/saved_agent_group_revival_modal.py` — builds the option list (`_create_options`), picks the
  first/highlighted option, and routes selection. Section order, headings, and empty-states live here.
- `src/sase/ace/tui/modals/saved_agent_group_revival_rendering.py` — `format_saved_group_row` builds each row's Rich
  `Text`; sibling helpers build the preview and the time/status labels.
- `src/sase/ace/tui/styles.tcss` — `SavedAgentGroupRevivalModal` block (panel widths, borders, headings).
- `tests/ace/tui/modals/test_saved_agent_group_revival_modal.py` — unit tests asserting exact option ordering and row
  text.
- `tests/ace/tui/visual/test_ace_png_snapshots_saved_groups.py` — PNG snapshot tests + fixtures for the modal.

### Current behavior (what we are changing)

The list is built in `_create_options()` in this order:

1. **Recent dismissals** heading, then recent rows (or a "No recent dismissals" empty row).
2. **Saved groups** heading, then saved rows (or a "No saved groups yet" empty row).
3. A "Load more saved groups..." row (only when more pages exist) and a "Custom revival search..." row.

There are no blank lines between sections, so the three groups visually run together.

Each row (`format_saved_group_row`) currently packs a lot onto one line, which frequently wraps in the narrow
(~46%-width) left pane:

```
 1. revived <name>  <generated-title>  1h | 05-27 12:00  recent  3 agents  done:2 failed:1  backend | revived x2
```

That is: an index number, a "revived" word, the title, a secondary generated-title, a relative+absolute timestamp, a
"recent" source word, an "N agents" count, spelled-out status counts, and a trailing hints blob (PRs/projects + revival
count). On a ~42-column option area this almost always overflows onto a second line.

This is presentation-only Textual/Rich work. The wire model (`SavedAgentGroupSummaryWire`) is unchanged and no
`sase-core` changes are required.

## Design goals

Make the left pane look like a clean, scannable table where every row fits on a single line.

1. **Section order + separation.** Show **Saved groups** first, then **Recent dismissals**, then the bottom actions
   ("Load more" when applicable + "Custom revival search"). Put a blank line between the three sections.
2. **Counts in the section headings.** Render headings as `Saved groups (N)` / `Recent dismissals (M)` so the user sees
   how many entries are in each section at a glance. Keep the existing empty-state rows when a section is empty.
3. **Compact, column-aligned rows that fit on one line.** Replace the dense free-form row with a small set of
   fixed-width leading columns followed by a flexible, ellipsis-truncated title. Fixed leading columns line up
   vertically down the list, giving a table-like, beautiful result; the title flows in the remaining width and truncates
   gracefully instead of wrapping.

### New row layout

Each row is a single-line `Text(no_wrap=True, overflow="ellipsis")` composed of these segments, left to right:

| Segment        | Width              | Style             | Notes                                                                                                                                                                                                                             |
| -------------- | ------------------ | ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| revived marker | 2                  | dim               | `↻ ` when the group was previously revived, else two spaces (keeps the title column aligned).                                                                                                                                     |
| age            | 4, right-justified | dim               | Relative only (`now`, `12m`, ` 5h`, ` 3d`, `10d`). The absolute date moves to the preview.                                                                                                                                        |
| agent count    | ~4, left-justified | cyan `#87D7FF`    | `×N` (e.g. `×3`). Unambiguous total agent count.                                                                                                                                                                                  |
| status badge   | ~7, padded         | per-status colors | Compact glyph+count tokens, highest-signal first: failed `✘`, running `●`, then done `✔`. Padded to a fixed cell width so the title column starts at the same x on every row. Falls back to a dim `—` when there are no statuses. |
| title          | remaining          | bold              | `name` when set, otherwise the generated title. Ellipsis-truncated.                                                                                                                                                               |

Concrete examples (the exact glyphs/widths are tuned against the regenerated PNG snapshot):

```
   3h  ×3  ✘1 ✔2   Backend batch
↻ 12m  ×2  ✔2       3 agents from @visual
   1d  ×6  ✘1 ●2    Big refactor sweep
```

Rationale for leading-metadata + trailing-title:

- Leading fixed columns align into clean vertical columns — scannable and table-like.
- Rich's `overflow="ellipsis"` truncates the **end** of the line, so putting the variable-length title last means long
  titles truncate cleanly while the metadata columns are always fully visible. No fragile manual title-width math.

Status glyphs/colors reuse the existing `_STATUS_COLORS` map and match the glyph vocabulary already used elsewhere in
the TUI (`✔` done / `✘` failed / `●` running). If the `↻` revived glyph renders wider than one cell in the pinned Fira
Code visual font (breaking column alignment), fall back to a one-cell ASCII marker — this is verified against the
snapshot during implementation.

Fields removed from the row but **retained in the preview pane**: the secondary generated-title (for named groups), the
absolute timestamp, the "recent" source word (now implied by the section heading), spelled-out status counts, and the
PR/project/revival hints blob. The per-row index number is dropped entirely (it restarted per section and added
clutter).

## Implementation plan

### 1. Rebuild the section structure and ordering — `saved_agent_group_revival_modal.py`

In `_create_options()`:

- Emit **Saved groups** first: a `Saved groups (N)` heading (disabled), then either saved rows or the
  `No saved groups yet` empty row, then the `Load more saved groups...` row when `self._next_cursor is not None`.
- Emit a blank-line separator (a disabled `Option(Text(""))` with a stable id, e.g. `sep:1`).
- Emit **Recent dismissals**: a `Recent dismissals (M)` heading (disabled), then either recent rows or the
  `No recent dismissals` empty row.
- Emit a second blank-line separator (`sep:2`).
- Emit the **Custom revival search...** action row last.

Disabled options are skipped automatically by the navigation mixin (it drives Textual's `action_cursor_down/up`), so
headings and blank separators are non-selectable and the cursor jumps over them.

Supporting updates in the same file:

- `format_saved_group_row(...)` calls no longer pass `source_label`/index (see step 2); update both call sites.
- `_first_option_id()` should return the first **saved** group, then the first recent group, then custom-search —
  matching the new top-to-bottom order so the initial preview matches the auto-highlighted row.
- `_update_preview_for_option_id(...)`: add the new separator ids to the set of ids that render no preview (alongside
  the existing heading ids). Headings/separators are disabled and never highlight, but keep this defensive and explicit.
- `_hints_text()`: keep the bottom hint bar, reorder its counts to `saved | recent` to match the new section order. Keep
  the load-more hint.

### 2. Compact row rendering — `saved_agent_group_revival_rendering.py`

- Rewrite `format_saved_group_row` to build the column layout above using `Text(no_wrap=True, overflow="ellipsis")`.
  Drop the `index` and `source_label` parameters. Keep the optional `now` parameter for deterministic tests.
- Add a small relative-age helper (e.g. `_row_age_label`) returning `now`/`Nm`/`Nh`/`Nd`, right-justified to the age
  column width. Reuse the existing `_parse_timestamp`; when the timestamp can't be parsed, fall back to the raw string
  (same resilience the current code has).
- Add a compact status-badge helper that emits up to the column's width budget of `glyph+count` tokens in priority order
  (failed, running, then done/others), padded to a fixed cell width for alignment, reusing `_STATUS_COLORS` /
  `_status_style`.
- Update the two section headings to include counts; keep heading color consistent with today's cyan accent.
- Remove helpers that become unused after the row rewrite (`_saved_group_row_time_label`, `_compact_hints`). Keep
  `_saved_group_time_label`, `_append_status_counts`, `_join_limited`, and the preview builders — the preview pane is
  unchanged.

### 3. Minor styling — `styles.tcss`

- Give the left list pane a little more room so compact rows breathe: widen `#saved-agent-group-list-panel` from `46%`
  toward `~50%` and reduce `#saved-agent-group-preview-panel` to match. Keep the existing borders/headings. Final
  percentages are confirmed against the regenerated snapshot. (Optional/tunable; only adjust if the snapshot shows the
  rows want the extra width.)

## Tests

### Unit tests — `tests/ace/tui/modals/test_saved_agent_group_revival_modal.py`

Update the assertions that pin the old ordering and row text to the new layout:

- `test_initial_page_includes_load_more_before_custom_search`: expect saved heading + saved rows + load-more first, then
  a separator, the recent heading and its empty row, a separator, and `custom-search` last. Load-more still precedes
  custom-search.
- `test_empty_state_still_keeps_custom_search_final`: expect the new id sequence (saved heading, saved empty, separator,
  recent heading, recent empty, separator, custom-search) and update the hint substring to the reordered counts.
- `test_load_more_appends_next_page_and_keeps_custom_final`: assert `custom-search` is the final id, the newly loaded
  group id is present, and `next_cursor` becomes `None` (the last saved row is no longer adjacent to custom-search now
  that Recent + actions sit below it).
- `test_enter_on_custom_search_returns_custom_result` and `test_enter_on_recent_group_returns_recent_location`: update
  the `highlighted` indices to the rows' new positions; the returned `SavedAgentGroupRevivalResult`s are unchanged.
- `test_row_rendering_includes_compact_saved_time`: assert the new compact age token (e.g. `1h`) and the `×N` count
  instead of the old `1h | 05-27 12:00` / `3 agents` strings.
- `test_named_row_uses_name_with_generated_summary_context`: the row now shows only the display title (the chosen
  `name`); assert the name is present and the generated subtitle is **not** in the row (it stays in the preview, which
  its own test already covers).

Preview-focused tests (`build_saved_group_preview`, `_saved_group_time_label` with supplied `now`, status style) stay as
they are.

### Visual snapshot tests — `tests/ace/tui/visual/test_ace_png_snapshots_saved_groups.py`

- Enrich the fixtures so the snapshot showcases the redesign: give the saved/recent summaries short, deterministic,
  age-like `created_at` values (so the relative-age column renders a stable, realistic token without wall-clock drift —
  the existing fixtures already rely on non-ISO `created_at` falling back to the raw string), plus a spread of agent
  counts, statuses (including a failed/running mix), and at least one named group to show the name-vs-generated-title
  behavior.
- Regenerate the four PNG goldens with `just test-visual --sase-update-visual-snapshots`, then **visually inspect** the
  actual PNGs (`saved_agent_group_revival_normal/empty/load_more/preview_rich`) to confirm: Saved-first ordering, blank
  lines between the three sections, single-line rows with aligned columns, and no wrapping. Iterate on the column widths
  / glyphs / panel split until it looks great before accepting the goldens.

### Repo checks

Run the focused modal + visual suites first, then, because this repo requires it after source changes, `just install`
(ephemeral workspace) followed by `just check`.

## Non-Goals

- No changes to the preview (right) pane content or to selection/Enter result semantics.
- No changes to the underlying wire model, the saved/recent group sort order computed in the backend, or any `sase-core`
  code — this is presentation-only.
- No new keymaps or `default_config.yml` changes (navigation, PgDn load-more, and Esc/q already exist).
- No memory-file changes.
