---
create_time: 2026-04-04 18:15:04
status: done
prompt: sdd/prompts/202604/vcs_mru_100_entries.md
---

# Plan: Expand VCS Xprompt MRU to 100 Entries & Fix Cycling Direction

## Problem

1. The VCS xprompt MRU only stores 10 entries — user wants at least 100.
2. `ctrl+p` first press shows the **oldest** entry instead of the **most recent**. The direction mapping is inverted
   relative to shell history convention (ctrl+p = go back in history = most recent first).

## Changes

### 1. Bump `_MAX_ENTRIES` from 10 to 100

**File:** `src/sase/history/vcs_xprompt_mru.py`

- Line 7: `_MAX_ENTRIES = 10` → `_MAX_ENTRIES = 100`
- Line 28: Update docstring "cap at 10" → "cap at 100"

Dedup and recency ordering are already correct — no logic changes needed here.

### 2. Fix ctrl+p / ctrl+n cycling direction

**File:** `src/sase/ace/tui/widgets/prompt_text_area.py` (lines 251-258)

Current behavior:

- `ctrl+n` → direction=+1 → first press goes to index 0 (most recent)
- `ctrl+p` → direction=-1 → first press goes to index `len-1` (oldest)

Fix: swap directions so ctrl+p walks forward through the MRU list (most recent → older) matching shell history
convention:

- `ctrl+p` → direction=+1 → first press goes to index 0 (most recent) ✓
- `ctrl+n` → direction=-1 → reverses back toward more recent entries

Concrete change:

```python
# Before
direction = 1 if event.key == "ctrl+n" else -1
# After
direction = -1 if event.key == "ctrl+n" else 1
```

The initial index fallback (`new_index = 0 if direction == 1 else len(mru) - 1`) remains correct after the swap since it
keys off `direction` value, not key name.

### 3. Update tests

**File:** `tests/test_vcs_xprompt_mru.py`

Tests already use `_MAX_ENTRIES` symbolically (imported from the module), so tests like `test_load_caps_at_max` and
`test_record_caps_at_max` will automatically work with the new value. No test changes needed.
