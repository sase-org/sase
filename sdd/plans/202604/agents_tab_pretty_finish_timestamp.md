---
create_time: 2026-04-27 08:59:13
status: done
prompt: sdd/prompts/202604/agents_tab_pretty_finish_timestamp.md
---
# Plan — Agents-tab finish-timestamp redesign

## Goal

Make the finish-timestamp shown to the left of each agent's runtime in the `sase ace` Agents-tab list look beautiful,
without growing wider than today.

Today's row (prior-day finish):

    sase (DONE) ×7 @h            260426T04:53:11 · 16m56s
                                 └── 15 cells ──┘

The `260426T04:53:11` (compact ISO-ish `YYMMDDTHH:MM:SS`) is the eyesore. It is high-density but hostile: the `T`
separator, lowercase numeric date, and no whitespace make it read like a log identifier rather than a time.

## Design

Tiered, recency-aware format. The narrower a tier's information needs, the narrower its rendered width — never wider
than today's 15-cell prior-day slot.

| Recency tier             | Format         | Example        | Width |
| ------------------------ | -------------- | -------------- | ----- |
| Same calendar day        | `HH:MM:SS`     | `04:53:11`     | 8     |
| Different day, same year | `Mon DD HH:MM` | `Apr 26 04:53` | 12    |
| Different year           | `Mon DD 'YY`   | `Apr 26 '25`   | 10    |

Why this is "much better":

- Uses an English month abbreviation (`Apr`) instead of a numeric `04` chunk glued to a day with no separator.
  Human-readable at a glance.
- Drops the `T` separator and the seconds for prior-day rows — when a row finished hours or days ago, second-level
  precision is noise, not signal. Same-day rows keep `:SS` because a row that finished 12 seconds ago vs. 4 minutes ago
  is meaningfully different in a live workflow.
- Reclaims 3 cells in the prior-day case and 5 cells in the cross-year case. Strictly narrower than today everywhere.
- Reuses the _exact_ style established by the existing `format_wait_until` helper in the same module (`%b %-d %H:%M`),
  so the visual vocabulary of the Agents tab stays internally consistent. The wait-until banner and the row-suffix
  timestamps will now look like they belong together.

### Styling — split into date prefix vs. time

Today the whole timestamp renders in `_RUNTIME_TS_STYLE = "#8787AF"` (muted lavender-steel). New design renders in two
tones:

- **Date prefix** (`Apr 26 ` / `Apr 26 '25`): a softer, dimmer variant of the current timestamp color. Carries the
  "context" weight — _which day_ did this finish on. Reading the date is a deliberate act, not the first thing the eye
  lands on.
- **Time** (`04:53` / `HH:MM:SS`): keeps the existing `#8787AF`. This is the more salient part of the timestamp because
  it's the chronological position within the day, which is what the user actually scans for when comparing rows.
- The `·` delimiter and the elapsed half stay unchanged.

This produces a soft visual hierarchy without adding any new bright colors to the Agents tab — the column reads as _one
thing_ (metadata) but with internal structure.

For the cross-year tier the format is _all date_ and no time, so we render the entire string in the dim "date prefix"
style. This keeps very-old rows visually quieter than recent rows, which matches their relative importance.

## Files to change

### 1. `src/sase/ace/tui/models/agent.py`

#### `_format_finish_timestamp(stop, now=None)` (lines 43–53)

Change return type from `str` to `tuple[str, str]`:

- `("", "HH:MM:SS")` for same-day finishes.
- `("Mon DD ", "HH:MM")` for prior-day, same-year finishes (note trailing space on the prefix — owns its own separator
  from the time half so the rendering layer can emit two `Text.append` calls without inserting a space of its own).
- `("Mon DD 'YY", "")` for cross-year finishes (no trailing space; the whole thing is "the date" and there is no time
  half).

Use `strftime` directives:

- Same-day: `("", stop.strftime("%H:%M:%S"))`
- In-year: `(stop.strftime("%b %-d "), stop.strftime("%H:%M"))`
- Cross-year: `(stop.strftime("%b %-d '%y"), "")`

Notes:

- `%-d` (Linux/macOS GNU strftime) drops the leading zero on the day so it reads `Apr 6` not `Apr 06`. The existing
  `start_time_compact` and `format_wait_until` helpers in this same module already use `%-d`, so the platform support is
  already a project assumption.
- English month abbreviations are fine; the rest of the TUI is English only and `%b` follows process locale, which is
  `C` in CI.

#### `compute_row_runtime(...)` (lines 56–83)

Change the `timestamp` half of the return tuple to be the new `tuple[str, str]` shape. Public return type becomes
`tuple[tuple[str, str] | None, str | None]`.

Rationale for keeping the model layer string-only (no `rich.text.Text`): the model module has zero `rich` imports today
and exists to be cheaply testable. Moving styling into the model would couple it to the renderer. Instead we hand the
renderer two strings and let it apply styles.

### 2. `src/sase/ace/tui/widgets/_agent_list_rendering.py`

#### Add a new style constant next to `_RUNTIME_TS_STYLE` (line 55)

```python
_RUNTIME_TS_STYLE = "#8787AF"          # existing — used for HH:MM portion
_RUNTIME_DATE_STYLE = "dim #8787AF"    # new — date prefix half, softer
_RUNTIME_ELAPSED_STYLE = "bold #BCBCBC"  # existing
```

`dim` of the same hex preserves the family (so the column still reads as one piece) while clearly de-emphasizing the
date prefix. We avoid picking a brand-new color so we don't inflate the Agents-tab palette.

#### `_build_runtime_suffix(agent, now=None)` (lines 169–180)

Adapt to the new `compute_row_runtime` return shape:

```python
ts_pair, elapsed = compute_row_runtime(agent, now=now)
suffix = Text()
if ts_pair is None and elapsed is None:
    return suffix
if ts_pair is not None:
    date_part, time_part = ts_pair
    if date_part:
        suffix.append(date_part, style=_RUNTIME_DATE_STYLE)
    if time_part:
        suffix.append(time_part, style=_RUNTIME_TS_STYLE)
    suffix.append(" · ", style=_RUNTIME_TS_STYLE)
if elapsed is not None:
    suffix.append(elapsed, style=_RUNTIME_ELAPSED_STYLE)
return suffix
```

The cell-width contract (`suffix.cell_len`) used by `assemble_padded_option` keeps working unchanged because Rich `Text`
tracks total cell length across appended segments.

### 3. `tests/ace/tui/widgets/test_agent_list_runtime.py`

Update the three timestamp-shape assertions and add a cross-year case:

- `test__format_finish_timestamp_same_day` → `assert _format_finish_timestamp(stop, now=now) == ("", "20:17:03")`.
- `test__format_finish_timestamp_prior_day` (rename → `_prior_day_same_year`) → assert `("Apr 24 ", "20:17")`. Drops the
  seconds — explicitly part of the new contract.
- New: `test__format_finish_timestamp_prior_year` → with `stop = 2025-12-31 20:17:03` and `now = 2026-04-25 09:00:00`,
  assert `("Dec 31 '25", "")`.
- `test_compute_row_runtime_finished_today` → assert `ts == ("", "20:17:03")`.
- `test_compute_row_runtime_finished_yesterday` → assert `ts == ("Apr 24 ", "20:17")`.
- `test_format_agent_option_finished_suffix_has_timestamp_and_elapsed` (line 126) → today's-finish case, assert
  `suffix.plain == "20:17:03 · 6h17m"` (unchanged for same-day; the user- visible string is identical for that tier).
- Add a sibling test for the prior-day tier asserting the rendered `suffix.plain == "Apr 24 20:17 · 38m45s"` so we lock
  in the no-`T`, human-readable shape end-to-end.
- `test_update_list_right_aligns_suffixes_across_batch` (line 156) — the same-day finish in this test is unaffected;
  assertions stay as-is.

### 4. Verification

- `grep -rn "_format_finish_timestamp\|compute_row_runtime" src tests` — already done; only the three files above
  reference these symbols.
- Confirm no consumer is parsing the returned strings (e.g. expecting the legacy `T` separator). Quick scan: only the
  renderer consumes them.
- Run `just check` from the workspace root.

## Open questions — resolved

- **Return shape**: `tuple[str, str]` (not a Rich `Text`) so the model layer stays renderer-agnostic. ✓
- **Locale**: rely on `%b` with the process locale; this matches the existing `format_wait_until` and
  `start_time_compact` helpers. ✓
- **Cross-year tier shows time?**: No — cross-year finishes are old enough that wall-clock time is meaningless and the
  date alone is the meaningful signal. Saves cells too. ✓
- **"Yesterday" / "this week" tier (e.g. `Yst 04:53` / `Mon 04:53`)?**: Not in this change. The win we're shipping is
  killing the `260426T04:53:11` look; adding a third intermediate tier would add cognitive load (users now have to learn
  what "Mon" vs `Apr 26` means without a clear rule for the boundary). The two-tier design is the smallest change that
  lands the visual upgrade.

## Out of scope

- Refactoring the rest of the runtime suffix (elapsed half, padding algorithm, banner alignment).
- Touching the `Timestamps:` block in the right detail panel (`agent.timestamps_display`) — those are full
  `%Y-%m-%d %H:%M:%S` on purpose because they are reference data, not a scanned column.
- Editing `format_wait_until` / `start_time_compact` — already use the same human-readable style, no work needed.
