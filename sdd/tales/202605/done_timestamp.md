---
create_time: 2026-05-12 19:09:09
status: done
prompt: sdd/prompts/202605/done_timestamp.md
---
# Rename Agent END Timestamp To DONE

## Context

ACE agent metadata currently renders lifecycle timestamps as fixed-width labels such as `START`, `RUN`, `PLAN`, `CODE`,
and `END`. The terminal lifecycle status is already `DONE`, so the completion timestamp label should also be `DONE`.

The active implementation surface is narrow:

- `src/sase/ace/tui/models/agent.py` builds `Agent.timestamps_display` and appends the completion row as `END`.
- `tests/test_agent_model_timestamps.py` asserts timestamp label order in the metadata display.
- `docs/ace.md` documents the metadata-panel timestamp labels.

Other exact `END` occurrences are unrelated and should not be renamed:

- Date range syntax: `START..END` in logs/config docs and CLI help.
- SQL `CASE ... END` text in bead database code.
- Embedded workflow ordering comments such as VCS-at-`END`.
- Historical SDD notes and prompt examples.

This does not require Rust core work. The label is presentation-only Textual/Python state, while persisted agent
metadata still uses fields such as `stop_time` and `stopped_at`.

## Desired Behavior

The metadata panel should show a completed agent's final timestamp as:

```text
DONE  | 2026-05-12 10:00:00
```

instead of:

```text
END   | 2026-05-12 10:00:00
```

The timestamp remains chronologically last after `START`, `WAIT`, `RUN`, `PLAN`, `FBACK`, `QUEST`, `RETRY`, `CODE`, and
`EPIC` entries. Only the display tag changes; runtime math, date bucketing, status bucketing, dismissal, revive, archive
serialization, and `stop_time` storage semantics remain unchanged.

## Implementation Plan

1. Update `Agent.timestamps_display`
   - Change the docstring bullet from `END shown for DONE/FAILED agents` to `DONE shown for completed agents`.
   - Change the terminal row formatter from `_fmt("END", self.stop_time.strftime(fmt))` to `_fmt("DONE", ...)`.
   - Keep `tag_width = 5`; `DONE` remains aligned with the existing five-character labels.

2. Update tests
   - Replace expected `END` timestamp tags with `DONE` in `tests/test_agent_model_timestamps.py`.
   - Add or keep a direct assertion that a completed agent's `timestamps_display` includes a `DONE` terminal row, so the
     label contract is explicit.
   - Preserve tests that omit `stop_time`; they should still produce no terminal completion row.

3. Update docs
   - In `docs/ace.md`, replace the metadata-panel bullet `END — when execution completed` with
     `DONE — when execution completed`.
   - Do not touch `START..END` date range documentation or unrelated generic uses of "end".

4. Verification
   - Run the focused test file:

     ```bash
     pytest tests/test_agent_model_timestamps.py
     ```

   - Run an exact scan for active display-label leftovers:

     ```bash
     rg -n '\bEND\b' src/sase/ace/tui/models tests/test_agent_model_timestamps.py docs/ace.md
     ```

     Expected remaining matches are only unrelated prose in `docs/ace.md` outside the metadata timestamp label section,
     if any.

   - Because this repo requires it after file changes, run:

     ```bash
     just install
     just check
     ```

## Risks And Notes

- This is intentionally not a global `END` to `DONE` rename. A global replacement would corrupt date-range syntax,
  comments, SQL, and workflow semantics.
- Internal names like `stop_time`, `stopped_at`, and `duration_display` should remain as-is. Renaming them would create
  a broader storage/API change without improving the user-facing lifecycle label consistency requested here.
- Historical SDD files and old prompt screenshots can remain historical records unless the user explicitly wants an
  archival rewrite.
