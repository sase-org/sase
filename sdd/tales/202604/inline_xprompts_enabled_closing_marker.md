---
create_time: 2026-04-03 11:45:38
status: done
prompt: sdd/prompts/202604/inline_xprompts_enabled_closing_marker.md
---

# Fix: `@` file ref validation fails on content inside disabled regions with inline closing marker

## Problem

The `%xprompts_enabled:false`/`true` disabled region protection fails when the closing `%xprompts_enabled:true` marker
is inline (at the end of a content line) rather than on its own line. This causes `@` references inside the disabled
region to be visible to the file reference validator, which incorrectly flags them as duplicates or missing files.

**Example failing prompt:**

```
%xprompts_enabled:false

### Change 1: ...
...should be internationalized using the @i18n attribute.
...
...should be internationalized using the @i18n attribute.
...
...consistency with the DRX grid system. %xprompts_enabled:true
```

The validator sees `@i18n` twice and terminates the workflow with a duplicate reference error.

## Root Cause

The `_DISABLED_REGION_RE` regex in `src/sase/xprompt/_disabled_regions.py` requires `%xprompts_enabled:true` to be at
the start of a line (`^[ \t]*`). When it appears inline, the regex doesn't match, so the region isn't protected.

The `strip_disabled_region_markers()` function has the same start-of-line assumption for its stripping regex.

## Plan

### Phase 1: Fix `_DISABLED_REGION_RE` to match inline closing markers

**File**: `src/sase/xprompt/_disabled_regions.py`

Update the regex so `%xprompts_enabled:true` can appear either at the start of a line OR after whitespace within a line:

- `^[ \t]*` before the closing marker becomes `(?:^[ \t]*|[ \t]+)` — match at line start with optional whitespace, or
  preceded by at least one whitespace character inline.

### Phase 2: Fix `strip_disabled_region_markers()` to strip inline closing markers

**File**: `src/sase/xprompt/_disabled_regions.py`

Update the stripping regex to handle both whole-line markers and inline markers using alternation:

1. **Whole-line markers** (existing): start-of-line marker removes the entire line
2. **Inline markers** (new): `[ \t]+%xprompts_enabled:...` removes the marker and preceding whitespace, preserving the
   rest of the line

### Phase 3: Add tests

**File**: `tests/test_disabled_regions.py`

1. `protect_disabled_regions()` with inline `%xprompts_enabled:true`
2. `strip_disabled_region_markers()` with inline markers
3. Integration test: `preprocess_prompt_late()` with `file_ref_mode="validate"` doesn't fail on `@` references inside a
   disabled region with an inline closing marker
