---
create_time: 2026-04-02 19:59:28
status: done
prompt: sdd/prompts/202604/timestamps_show_last_collapsed.md
---

# Plan: Always Show Last TIMESTAMPS Entry When Collapsed

## Problem

The TIMESTAMPS section's COLLAPSED fold level currently shows zero entries — just `TIMESTAMPS: [folded: N]`. This hides
the most useful piece of information: what happened most recently. Users have to expand the section just to see the
latest timestamp.

## Design

Change COLLAPSED behavior to always render the **last** (most recent) entry in `changespec.timestamps`, with a folded
count for the remaining hidden entries.

### Visual examples

**Before (multiple entries):**

```
TIMESTAMPS: [folded: 4]
```

**After (multiple entries):**

```
TIMESTAMPS:
  ...                          [folded: 3]
  [260329_101500] REWIND  (3)
```

**After (single entry):**

```
TIMESTAMPS:
  [260329_100000] COMMIT  (1)
```

### Implementation

**`src/sase/ace/tui/widgets/timestamps_builder.py`**

1. Extract the per-entry rendering logic (lines 78-95) into a `_render_entry(text, entry)` helper so COLLAPSED can reuse
   it without duplication.

2. Modify the COLLAPSED branch (lines 62-66):
   - Render `TIMESTAMPS:\n` header (same as EXPANDED/FULLY_EXPANDED)
   - If there are hidden entries (len > 1), render a `...  [folded: N-1]` line
   - Call `_render_entry()` for the last entry

**`tests/ace/tui/test_timestamps_builder.py`**

3. Update existing `test_collapsed_shows_folded_count`: expect the last entry visible and folded count = N-1.
4. Add `test_collapsed_single_entry_no_folded_indicator`: single entry shows just that entry, no folded text.
5. Add `test_collapsed_shows_last_entry_not_first`: multiple entries, verify the last entry's detail appears and the
   first entry's detail does not.
