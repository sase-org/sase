---
create_time: 2026-03-30 16:12:07
status: done
---

# Fix: TIMESTAMPS field not showing in sase ace TUI (hybrid format gap)

## Problem

TIMESTAMPS fields with entries written during the format migration transition are invisible in the `sase ace` TUI. The
section doesn't render at all — no header, no entries.

## Root Cause

The TIMESTAMPS parser (`section_parsers.py:parse_timestamps_line`) handles two formats but misses a third:

| Format                        | Example                                | Regex matches? |
| ----------------------------- | -------------------------------------- | -------------- |
| New (bracketless)             | `260330_102053 SYNC   success`         | Yes            |
| Old (bracketed YYYY-MM-DD)    | `[2026-03-30 10:20:53] SYNC   success` | Yes            |
| **Hybrid (bracketed YYMMDD)** | `[260330_102053] SYNC   success`       | **No**         |

The hybrid format was produced when `generate_timestamp()` (returning `YYMMDD_HHMMSS`) was used with the old bracket
template (`f"  [{ts}] ..."`) during the migration transition window — before commit 3744528a landed both changes
atomically.

Since no entries parse, `changespec.timestamps` is empty, and `build_timestamps_section()` exits at the
`if not changespec.timestamps` guard — making the section completely invisible.

## Fix

### Phase 1: Parser regex — `src/sase/ace/changespec/section_parsers.py`

Add a hybrid-format regex to `parse_timestamps_line()` matching `[YYMMDD_HHMMSS]`:

```python
hybrid_match = re.match(
    r"^\[(\d{6}_\d{6})\]\s+"
    r"(COMMIT|STATUS|SYNC|REWORD|REWIND)\s+"
    r"(.+)$",
    stripped,
)
ts_match = new_match or old_match or hybrid_match
```

### Phase 2: Insert-point regex — `src/sase/ace/timestamps/recording.py`

Update `_find_timestamps_insert_point()` line 109 to also detect hybrid entries:

```python
if re.match(r"^\s+(?:\[\d{4}-\d{2}-\d{2}|\[?\d{6}_\d{6})", line):
```

### Phase 3: Tests — `tests/ace/changespec/test_timestamps.py`

Add `test_parse_timestamps_hybrid_format()` and `test_find_timestamps_insert_appends_to_hybrid_format()` covering the
bracketed compact format.

### Phase 4: Verify

`just install && just check`
