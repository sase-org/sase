---
create_time: 2026-03-30 14:59:20
status: done
prompt: sdd/prompts/202603/timestamps_format_migration.md
---

# Migrate TIMESTAMPS Field to YYMMDD_HHMMSS Format

## Goal

Migrate ChangeSpec TIMESTAMPS entries from `[YYYY-MM-DD HH:MM:SS]` format to `YYMMDD_HHMMSS` format, matching the format
used by HOOKS status lines and other internal timestamps.

### Before

```
TIMESTAMPS:
  [2026-03-29 14:30:22] COMMIT  (1)
  [2026-03-29 14:32:15] STATUS  WIP -> Draft
```

### After

```
TIMESTAMPS:
  260329_143022 COMMIT  (1)
  260329_143215 STATUS  WIP -> Draft
```

## Motivation

The HOOKS field already uses `YYMMDD_HHMMSS` (e.g., `(1) [260315_092521] PASSED (3s)`), and the core utility
`sase.core.time.generate_timestamp()` already produces this format. The TIMESTAMPS field should be consistent.

## Design

### Format details

- Drop the square brackets around timestamps (HOOKS uses brackets for display but the raw value is `YYMMDD_HHMMSS`)
- Use `generate_timestamp()` from `sase.core.time` instead of the custom `get_current_display_timestamp()`
- Separator between timestamp and event type is a single space (since YYMMDD_HHMMSS is a fixed 13-char width, alignment
  is maintained naturally)

### Backward compatibility

The parser must accept **both** the old `[YYYY-MM-DD HH:MM:SS]` format and the new `YYMMDD_HHMMSS` format, since
existing `.gp` files contain entries in the old format. Old entries are parsed as-is (stored with their original
timestamp string). New entries are written in the new format only.

The `_find_timestamps_insert_point()` regex in `recording.py` that detects existing entries also needs dual-format
support.

## Changes

### Phase 1: Recording (write path)

**`src/sase/ace/timestamps/recording.py`**

- Remove `get_current_display_timestamp()` — replace with `generate_timestamp()` from `sase.core.time`
- Update `format_timestamp_entry_line()` to emit `  YYMMDD_HHMMSS EVENT  detail\n` (no brackets)
- Update `_find_timestamps_insert_point()` regex to match both old and new formats

### Phase 2: Parsing (read path)

**`src/sase/ace/changespec/section_parsers.py`**

- Update `parse_timestamps_line()` regex to accept both formats:
  - Old: `[YYYY-MM-DD HH:MM:SS] EVENT  detail`
  - New: `YYMMDD_HHMMSS EVENT  detail`

### Phase 3: Formatting (serialization)

**`src/sase/ace/timestamps/formatting.py`**

- Update `format_timestamps_field()` to emit `  {timestamp} {padded_event}{detail}` (no brackets)
- Note: this serializes whatever timestamp string is stored in the model, so old-format entries round-trip as-is

### Phase 4: TUI display

**`src/sase/ace/tui/widgets/timestamps_builder.py`**

- Update the display line from `[{entry.timestamp}] ` to `{entry.timestamp} ` (no brackets)

### Phase 5: Tests

**`tests/ace/changespec/test_timestamps.py`**

- Update all test fixtures and assertions to use the new format
- Add a test that verifies backward-compatible parsing of old-format entries
- Keep the existing test structure (parsing, formatting, atomic recording)

### Phase 6: Documentation

**`docs/change_spec.md`**

- Update the TIMESTAMPS section (lines 297-322) to show the new format
- Update the format description from `YYYY-MM-DD HH:MM:SS` to `YYMMDD_HHMMSS`
