---
create_time: 2026-04-25 20:23:52
status: done
prompt: sdd/prompts/202604/agents_tab_runtime_timestamp.md
---
# Plan: Right-aligned runtime + finish-timestamp on the Agents tab

## Goal

For every selectable row on the Agents tab of `sase ace`, append a small, right-aligned, dim suffix that answers "how
long?" and "when did it finish?" at a glance — without competing visually with the existing left-side content (name,
status, badges, annotations).

## User-visible behavior

Two row states, two suffix shapes:

| Row state                                                              | Right-side suffix             | Example                    |
| ---------------------------------------------------------------------- | ----------------------------- | -------------------------- |
| Active (RUNNING, PLANNING, WAITING, QUESTION, RETRYING, PLAN APPROVED) | `<elapsed>`                   | `38m45s`                   |
| Finished today (DONE, PLAN DONE, FAILED, …)                            | `HH:MM:SS · <elapsed>`        | `20:17:03 · 38m45s`        |
| Finished a prior day                                                   | `YYMMDDTHH:MM:SS · <elapsed>` | `260424T20:17:03 · 38m45s` |

- "Today" is determined relative to the local clock the TUI is rendering on.
- For active rows, the elapsed value ticks naturally — the existing periodic agent-list refresh (the one that drives
  "auto-refresh in Ns") already rebuilds the rows; no new timer is needed.
- Workflow children, retry-chain rows, and attempt-history rows follow the same rule using their own `start_time` /
  `stop_time` (or `start_epoch` / `end_epoch` for `AttemptRecord`).
- Banner rows (tag/project/name-root) get **no** suffix — they continue to pad with their decorative rule (`═`, `─`,
  dot-padding).

## Visual / styling design

The suffix is intentionally low-contrast so it reads as "metadata" and never upstages the agent's name or status.

- **Dim grey** (`dim #808080`) for the timestamp half — same color already used for retry/workflow indents, so it nests
  naturally with existing visual hierarchy.
- **Dim** (no explicit color) for the elapsed half so the terminal's default fg-mute applies — readable on any theme.
- **Bullet separator** `·` between timestamp and elapsed (already used for attempt rows, so the language is consistent).
- **At least 2 spaces** between the row's left content and the suffix — if the left content already runs long, the
  suffix still gets breathing room.
- The right edge of the suffix is aligned to the **agent list widget's current rendered width** (the same width the
  banner rows pad to today). When the user resizes the pane, the next refresh re-aligns.

The result is a column-like effect without needing real columns: every row looks like
`[badges] name (status) ………………… 20:17:03 · 38m45s`.

## Information already available

Everything we need is in `Agent` / `AttemptRecord` (see `src/sase/ace/tui/models/agent.py`):

- `Agent.start_time: datetime | None` – row's begin time
- `Agent.run_start_time: datetime | None` – when WAITING flipped to RUNNING
- `Agent.stop_time: datetime | None` – DONE/FAILED end
- `AttemptRecord.start_epoch / end_epoch` – per-attempt timing
- Existing helper `format_compact_duration(seconds)` already produces `1h05m` / `38m45s` / `12s` — reuse verbatim.

Which start to use for elapsed:

- Use `run_start_time` when present (so a long WAIT period doesn't inflate what looks like "runtime"); fall back to
  `start_time`.
- Active rows: `now - effective_start`.
- Finished rows: `stop_time - effective_start`.

## Implementation outline

The change is concentrated in three files:

1. **`src/sase/ace/tui/models/agent.py`** — add two small formatter helpers that return strings (no Rich knowledge):
   - `format_finish_timestamp(stop: datetime, now: datetime | None = None) -> str`
     - Same day: `"%H:%M:%S"`
     - Different day: `"%y%m%dT%H:%M:%S"`
   - `compute_row_runtime(agent) -> tuple[str | None, str | None]` returning `(timestamp_or_none, elapsed_or_none)`.
     Returns `(None, None)` when `start_time is None` or for pre-run states where showing a clock would be misleading
     (today: just `WAITING` before `run_start_time` is known).

   Both get a small unit-test set against fixed `datetime` inputs.

2. **`src/sase/ace/tui/widgets/_agent_list_rendering.py`** — extend the row formatters to return the row text _plus_ its
   right suffix as a `Text`, so the caller can pad and concatenate. Two viable shapes:
   - **(A)** Add a new `width: int` kwarg to `format_agent_option` / `format_attempt_option`. The function builds the
     left content as today, computes the suffix, then appends `" " * pad + suffix` where
     `pad = max(2, width - left.cell_len - suffix.cell_len)`.
   - **(B)** Have the formatters return a `(left_text, suffix_text)` tuple and let `agent_list.py` do the padding after
     measuring all rows (so suffix alignment can use the _real_ max width of the batch instead of a passed-in width).

   **Recommendation: (B).** It keeps measurement and padding in one place (`agent_list.update_list`) — the same place
   that already computes `max_width` and `banner_width`. It also lets the suffixes line up with each other even when
   individual rows are shorter than the widget.

3. **`src/sase/ace/tui/widgets/agent_list.py`** — in `update_list`:
   - First pass: build `(left, suffix)` per row, track `max_left = max(left.cell_len)` and
     `max_suffix = max(suffix.cell_len)`.
   - Compute `target_width = max(_MIN_BANNER_WIDTH, max_left + 2 + max_suffix)`.
   - Second pass: for each row, append `" " * (target_width - left.cell_len - suffix.cell_len)` then the suffix; emit as
     a single `Option`.
   - Use `target_width` for `banner_width` so banner rules also stretch to the new wider width.
   - The existing `optimal_width = banner_width + _PADDING` line then naturally accounts for the suffix — the widget
     resize message will request a slightly wider pane (a few cells), which is the desired effect.

   Attempt rows already show `Attempt N · 14:30:45 · failed: …`. Keep that left content unchanged and append a dim
   duration suffix (`end_epoch - start_epoch`) on the right, using the same alignment logic.

## Test plan

New tests under `tests/ace/tui/widgets/`:

- `test_agent_list_runtime.py`
  - Active agent → suffix is a single `format_compact_duration` value.
  - Finished today → suffix is `HH:MM:SS · <dur>`.
  - Finished yesterday → suffix is `YYMMDDTHH:MM:SS · <dur>`.
  - `start_time = None` (or pure WAITING) → no suffix at all.
  - Suffixes across a batch right-align to the same column.
- `test_agent_list_attempts.py` (existing) — extend to assert the new duration tail on attempt rows.

Tests follow the existing string-match-on-`option.prompt.plain` pattern; no snapshot framework introduced.

## Edge cases & non-goals

Edge cases handled explicitly:

- `start_time is None` → no suffix (don't render `?`).
- `WAITING` before run actually starts (`run_start_time is None`) → no suffix; the existing inline "(until 14:30, 12m)"
  annotation already carries the relevant timing.
- Banner rows → no suffix; existing rule-padding wins.
- Workflow parent vs. child → each renders its own; no aggregation.
- Retry rows → use the row's own start/stop, not the chain root's.
- Suffix `cell_len` is measured via Rich's existing `Text.cell_len` to handle multi-byte separators correctly.

Non-goals (call out so they don't scope-creep):

- No change to the metadata-panel `timestamps_display` (that one is already verbose by design).
- No change to the periodic refresh interval — running rows already re-render frequently enough that the elapsed value
  feels live.
- No new ChangeSpec/CLI surface; this is a TUI presentation change only.
- Do not change footer keybindings or help-modal copy (no new key).

## Files touched (anticipated)

- `src/sase/ace/tui/models/agent.py` (+ ~25 LOC helpers)
- `src/sase/ace/tui/widgets/_agent_list_rendering.py` (~50 LOC, return shape change)
- `src/sase/ace/tui/widgets/agent_list.py` (~20 LOC, padding pass)
- `tests/ace/tui/widgets/test_agent_list_runtime.py` (new)
- `tests/ace/tui/widgets/test_agent_list_attempts.py` (extended)

## Risks

- Width math: the agent-list widget posts a `WidthChanged` message that drives the pane size. Adding ~16 cells of suffix
  could push past the `_MAX_AGENT_LIST_WIDTH = 80` clamp on long names. **Mitigation**: rendering already truncates at
  `_MAX_AGENT_LIST_WIDTH`; verify visually that suffix still shows when names are long, and if not, fall back to showing
  only the elapsed value (drop the timestamp half) for finished rows once `left + suffix > 80 - _PADDING`.
- Banner-width interaction: banners use the same `banner_width`, so they pad to the same column. Confirmed in
  `format_banner_option` — no new code needed there.
