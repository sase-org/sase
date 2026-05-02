---
create_time: 2026-03-30 13:55:40
status: done
prompt: sdd/prompts/202603/fix_folded_count_color.md
---

# Plan: Fix TIMESTAMPS Folded Count Color

## Problem

The `[folded: 2]` text next to `TIMESTAMPS:` is styled with `"italic #AF87D7"` (purple), matching the timestamp color.
But this folded count indicator is structural metadata, not a timestamp — it should use the same dim style
(`"italic #808080"`) that every other section uses for its folded count.

### Current state

| Section    | Folded count style       |
| ---------- | ------------------------ |
| COMMITS    | `italic #808080`         |
| HOOKS      | `italic #808080`         |
| MENTORS    | `italic #808080`         |
| TIMESTAMPS | `italic #AF87D7` (wrong) |

The purple was introduced in the previous change because the plan called for changing both `_COLOR_TIMESTAMP` and the
folded count style. The folded count change was a mistake — it should have been left as `#808080`.

## Change

**File**: `src/sase/ace/tui/widgets/timestamps_builder.py` (line 62)

Change the folded count style from `"italic #AF87D7"` back to `"italic #808080"`, matching all other section builders.

## Verification

- `just install && just check`
- Visual verification via `sase ace` that `[folded: N]` is dim gray, not purple
