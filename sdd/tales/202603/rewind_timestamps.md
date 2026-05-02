---
create_time: 2026-03-30 14:51:01
status: done
prompt: sdd/prompts/202603/rewind_timestamps.md
---

# Plan: Track Rewinds in TIMESTAMPS Field

## Context

The ChangeSpec TIMESTAMPS field currently tracks four event types: COMMIT, STATUS, SYNC, and REWORD. Rewinds (`R` keymap
on CLs tab) are significant structural operations — they roll back commit history, delete entries, and create new
proposals — but leave no trace in the TIMESTAMPS audit trail.

## Goal

Add a fifth event type, **REWIND**, so the TIMESTAMPS timeline records when a rewind occurred and which entry was
rewound to.

## Design Decisions

### Detail format

Use `(N)` where N is the entry number rewound to, consistent with COMMIT's `(N)` format:

```
[2026-03-30 09:15:00] REWIND  (3)
```

This is clean, scannable, and tells the user exactly what they need: _when_ and _to where_. The COMMITS section itself
shows the structural aftermath (renumbered entries, new proposals), so the timestamp doesn't need to duplicate that.

### Color: `#FF8787` (soft coral)

The existing palette occupies cyan, gold, blue, and lavender. A warm coral signals "significant destructive action"
while remaining visually harmonious. Bold styling keeps it consistent with the other event types.

### Fold behavior: show at EXPANDED level

Currently EXPANDED shows only COMMIT entries. REWIND events should also appear at EXPANDED level because they are
structural changes to the commit history — equally important as COMMITs for understanding the timeline. Users who expand
TIMESTAMPS want to see the commit lifecycle, and rewinds are a core part of that.

So the fold behavior becomes:

- **COLLAPSED**: header with `[folded: N]` count (unchanged)
- **EXPANDED**: COMMIT + REWIND entries
- **FULLY_EXPANDED**: all entries (unchanged)

### Recording location: `RewindWorkflow.run()`

Record the timestamp inside the workflow after `rewind_commit_entries()` succeeds but before returning. This follows the
same pattern as COMMIT (recorded in `commit_utils/entries.py`) — the timestamp lives alongside the action logic, so it
fires regardless of how the rewind is triggered.

## Changes

### 1. Parser — recognize REWIND token

**`src/sase/ace/changespec/section_parsers.py`** — Add `REWIND` to the regex alternation in `parse_timestamps_line()`.

### 2. Model docstrings

**`src/sase/ace/changespec/models.py`** — Update `TimestampEntry` docstring to include a REWIND example line, and add
`"REWIND"` to the `event_type` field comment.

### 3. Recording docstring

**`src/sase/ace/timestamps/recording.py`** — Update `add_timestamp_entry_atomic()` docstring to list REWIND as a valid
event type.

### 4. TUI display — color + fold filtering

**`src/sase/ace/tui/widgets/timestamps_builder.py`**:

- Add `_COLOR_REWIND_EVENT = "bold #FF8787"` and map `"REWIND"` in `_EVENT_COLORS`.
- Update the EXPANDED filter to show both COMMIT and REWIND entries.

### 5. Workflow — record timestamp on success

**`src/sase/workflows/rewind/workflow.py`** — After `rewind_commit_entries()` succeeds (line ~169), call
`add_timestamp_entry_atomic(project_file, cl_name, "REWIND", f"({selected_entry_num})")`.

### 6. Tests

- **`tests/ace/changespec/test_timestamps.py`** — Add a REWIND entry to the parse round-trip fixture and verify it
  parses correctly.
- **`tests/ace/tui/test_timestamps_builder.py`** — Add REWIND entries to test data; verify EXPANDED shows REWIND
  alongside COMMIT; verify COLLAPSED count includes REWIND.
- **`tests/ace/changespec/test_timestamps.py`** — Add a REWIND entry to the formatting test to verify column alignment.
