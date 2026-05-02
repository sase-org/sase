---
create_time: 2026-03-29 18:46:47
status: done
---

# Plan: TIMESTAMPS `[folded: <N>]` indicator when collapsed

## Problem

When a ChangeSpec is completely folded (all sections at `FoldLevel.COLLAPSED`), the TIMESTAMPS section is not rendered
at all — zero visual footprint. Other sections like COMMITS, HOOKS, and MENTORS show their header with a `[folded: ...]`
indicator when collapsed. TIMESTAMPS should follow the same pattern: show `TIMESTAMPS: [folded: <N>]` where `<N>` is the
number of timestamp entries.

## Current behavior

In `timestamps_builder.py` line 57:

```python
if not changespec.timestamps or timestamps_fold == FoldLevel.COLLAPSED:
    return tracker
```

This early-returns when COLLAPSED, producing zero output.

## Desired behavior

When `timestamps_fold == FoldLevel.COLLAPSED` and the ChangeSpec has timestamps, render:

```
TIMESTAMPS: [folded: <N>]
```

where `<N>` is `len(changespec.timestamps)`.

## Changes

### Phase 1: Modify `timestamps_builder.py`

**File**: `src/sase/ace/tui/widgets/timestamps_builder.py`

Change the early return logic so that:

1. If `changespec.timestamps` is None/empty → still return early (no section to show)
2. If `timestamps_fold == FoldLevel.COLLAPSED` AND timestamps exist → render `TIMESTAMPS: [folded: <N>]\n` using the
   same styling conventions as other sections, then return

The collapsed rendering should be:

- `TIMESTAMPS:` in `_COLOR_HEADER` style (`bold #87D7FF`)
- `[folded:` in `italic #808080` style
- `<N>` in `italic #808080` style (just the count, simple like MENTORS)
- `]` in `italic #808080` style
- newline

### Phase 2: Add tests

**File**: `tests/ace/tui/test_timestamps_builder.py` (new file)

Add tests for the three fold levels:

1. `test_collapsed_shows_folded_count` — COLLAPSED with timestamps shows `TIMESTAMPS:` header with `[folded: N]`
2. `test_collapsed_no_timestamps_shows_nothing` — COLLAPSED with no timestamps shows nothing
3. `test_expanded_shows_commit_entries_only` — EXPANDED filters to COMMIT entries (existing behavior, verify not broken)
4. `test_fully_expanded_shows_all_entries` — FULLY_EXPANDED shows all entries (existing behavior, verify not broken)
