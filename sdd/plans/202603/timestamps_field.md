---
create_time: 2026-03-29 13:40:13
status: done
prompt: sdd/prompts/202603/timestamps_field.md
---

# Plan: TIMESTAMPS ChangeSpec Field

## Overview

Add a new `TIMESTAMPS` section to ChangeSpecs that serves as a chronological audit trail of lifecycle events. The
section tracks four event types: COMMITS entry creation, successful syncs, rewords (both description and tag variants),
and STATUS transitions.

## Design

### File Format

TIMESTAMPS is the last section in a ChangeSpec (after MENTORS). Entries are chronologically ordered, one per line, with
aligned columns for readability:

```
TIMESTAMPS:
  [2026-03-29 14:30:22] COMMIT  (1)
  [2026-03-29 14:32:15] COMMIT  (2)
  [2026-03-29 14:35:10] STATUS  WIP -> Draft
  [2026-03-29 15:00:00] SYNC    (2)
  [2026-03-29 15:10:00] REWORD  description
  [2026-03-29 15:15:00] REWORD  tag "Bug"
  [2026-03-29 15:20:00] COMMIT  (2a)
```

Key format choices:

- **Timestamp**: `YYYY-MM-DD HH:MM:SS` in square brackets (user-specified format, distinct from the internal
  `YYmmdd_HHMMSS` format used elsewhere)
- **Event type**: Fixed-width keyword, right-padded to 7 chars for alignment (`COMMIT `, `STATUS `, `SYNC   `,
  `REWORD `)
- **Detail**: Event-specific context (see below)
- **Arrow**: `->` for STATUS transitions (plain ASCII, avoids encoding issues in .gp files)

### Event Types and Details

| Event    | Detail Format                | Example                       | Trigger                                                     |
| -------- | ---------------------------- | ----------------------------- | ----------------------------------------------------------- |
| `COMMIT` | `(N)` or `(Na)` entry ID     | `COMMIT  (1)`, `COMMIT  (2a)` | `add_commit_entry_with_id()`, `add_proposed_commit_entry()` |
| `STATUS` | `OldStatus -> NewStatus`     | `STATUS  WIP -> Draft`        | `transition_changespec_status()`                            |
| `SYNC`   | `(N)` latest commit entry ID | `SYNC    (2)`                 | `_sync_task()` on success                                   |
| `REWORD` | `description` or `tag "X"`   | `REWORD  tag "Bug"`           | `reword_execute_task()`, `add_tag_task()`                   |

### Fold Behavior

TIMESTAMPS has its own fold state (`timestamps_collapsed`) with a dedicated fold key. The three levels:

- **COLLAPSED**: Section not rendered at all (zero visual footprint)
- **EXPANDED**: Header + only `COMMIT` entries shown (the most commonly needed audit info)
- **FULLY_EXPANDED**: Header + all entries shown

This matches the user's spec: "No entries when fully folded, only COMMITS creation when partially unfolded, all when
fully unfolded."

### TUI Rendering

Color palette per event type (chosen to be visually distinct and harmonious with the existing ChangeSpec color scheme):

| Element       | Color          | Rationale                                             |
| ------------- | -------------- | ----------------------------------------------------- |
| `TIMESTAMPS:` | bold `#87D7FF` | Matches all section headers                           |
| Timestamp     | dim `#808080`  | De-emphasized, timestamps are structural not semantic |
| `COMMIT`      | bold `#00D7AF` | Green tone — something was created                    |
| `STATUS`      | bold `#FFD787` | Gold/amber — state transition                         |
| `SYNC`        | bold `#5FD7FF` | Cyan — matches sync-related UI                        |
| `REWORD`      | bold `#D7AFFF` | Soft purple — content edit                            |
| Arrow (`->`)  | bold `#808080` | Structural, de-emphasized                             |
| Detail text   | `#D7D7AF`      | Matches note text style                               |

### Data Model

New dataclass `TimestampEntry` in `models.py`:

```python
@dataclass
class TimestampEntry:
    timestamp: str        # "YYYY-MM-DD HH:MM:SS"
    event_type: str       # "COMMIT", "STATUS", "SYNC", "REWORD"
    detail: str           # Event-specific detail string
```

Add `timestamps: list[TimestampEntry] | None = None` to the `ChangeSpec` dataclass.

## Implementation Phases

### Phase 1: Data Model and Parsing

**Files**: `models.py`, `section_parsers.py`, `parser.py`

- Add `TimestampEntry` dataclass to `models.py`
- Add `timestamps` field to `ChangeSpec`
- Add `parse_timestamps_line()` to `section_parsers.py` — parse `[YYYY-MM-DD HH:MM:SS] EVENT detail`
- Register `TIMESTAMPS:` as a section header in `parser.py`'s `_parse_section_header()` and `_parse_section_content()`
- Add `build_timestamp_entry()` helper for safe dict-to-dataclass conversion

### Phase 2: Formatting and Atomic Write

**Files**: New `src/sase/ace/timestamps/` module (or add to existing changespec utils)

- `format_timestamps_field()` — serialize `list[TimestampEntry]` back to .gp file format
- `add_timestamp_entry_atomic()` — the core recording function:
  1. Acquire `changespec_lock`
  2. Read file lines
  3. Find target ChangeSpec's TIMESTAMPS section (or create it)
  4. Append new entry line
  5. Write atomically
- `get_current_display_timestamp()` — returns `YYYY-MM-DD HH:MM:SS` using project timezone

### Phase 3: Event Integration

Five integration points, each calling `add_timestamp_entry_atomic()`:

1. **COMMITS creation** (`src/sase/workflows/commit_utils/entries.py`)
   - In `add_commit_entry_with_id()` — after successful entry insertion, record `COMMIT (N)`
   - In `add_proposed_commit_entry()` — record `COMMIT (Na)`

2. **STATUS changes** (`src/sase/status_state_machine/transitions.py`)
   - In `transition_changespec_status()` — after successful transition, record `STATUS Old -> New`
   - Must capture old status before the transition for the arrow format

3. **Sync success** (`src/sase/ace/tui/actions/sync.py`)
   - In `_sync_task()` — after successful sync (not on error/conflict), record `SYNC (N)` where N is the latest commit
     entry

4. **Reword** (`src/sase/ace/handlers/reword.py`)
   - In `reword_execute_task()` — after successful reword, record `REWORD description`

5. **Tag addition** (`src/sase/ace/handlers/reword.py`)
   - In `add_tag_task()` — after successful tag add, record `REWORD tag "TagName"`

### Phase 4: TUI Rendering

**Files**: New `src/sase/ace/tui/widgets/timestamps_builder.py`, update `section_builders.py`, `changespec_detail.py`

- Create `build_timestamps_section()` with fold-aware rendering
- Add `timestamps_collapsed` parameter threading through `_build_display_content()` and `update_display()`
- Render with the color palette described above
- Section appears after MENTORS in the display

### Phase 5: Fold State

**Files**: `fold_state.py`, keymap config, keybinding footer

- Add `timestamps_collapsed: FoldLevel` to fold state tracking
- Add fold key binding in `default_config.yml` (need to identify an available key)
- Update fold cycling logic
- Add to help modal if appropriate

### Phase 6: Tests

- Parser tests: round-trip parsing of TIMESTAMPS section
- Formatting tests: serialization matches expected .gp format
- Event recording tests: each event type produces correct entry
- Fold behavior tests: correct entries shown at each fold level

## Edge Cases

- **No TIMESTAMPS section yet**: First event creates the section header + entry
- **Archive files**: TIMESTAMPS are preserved when ChangeSpecs move to archive
- **Concurrent writes**: Uses existing `changespec_lock()` mechanism — safe
- **Empty detail**: Some events (like SYNC) might not always have meaningful detail; always include the entry ID when
  available
