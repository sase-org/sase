---
create_time: 2026-04-10 17:01:11
status: done
prompt: sdd/prompts/202604/changespec_suffix_match.md
---

# Plan: Fix ChangeSpec suffix mismatch in TUI keymaps

## Problem

When a ChangeSpec is created with a numeric suffix (e.g., `tcpm_launch_tests_1`) but later renamed to strip the suffix
(e.g., `tcpm_launch_tests` on status change to "Ready"), two TUI keymaps break:

1. **`<enter>` on Agents tab** — `navigate_to_changespec_tab()` tries to find a ChangeSpec matching the agent's
   `cl_name` (`tcpm_launch_tests_1`), but the current ChangeSpec is now named `tcpm_launch_tests`. Exact `==` match
   fails.

2. **`L` on CLs tab** — `_load_agents_for_cl()` tries to find agents matching the ChangeSpec name (`tcpm_launch_tests`),
   but agents still have `cl_name = "tcpm_launch_tests_1"`. Exact `==` match fails.

## Root Cause

Both directions use `==` exact matching. The existing `strip_reverted_suffix()` in `src/sase/core/changespec.py` already
handles stripping `_<N>` suffixes but isn't used for these lookups.

## Approach

Add a `changespec_names_match(a, b)` helper that returns True if:

- `a == b` (exact match), OR
- `strip_reverted_suffix(a) == b` or `strip_reverted_suffix(b) == a`

Important: we compare `strip(a) == b` rather than `strip(a) == strip(b)` to avoid false positives where `foo_1` and
`foo_2` would incorrectly match (both strip to `foo`).

## Phases

### Phase 1: Add `changespec_names_match()` helper

**File:** `src/sase/core/changespec.py`

Add after `strip_reverted_suffix()`:

```python
def changespec_names_match(name_a: str, name_b: str) -> bool:
    """Check if two ChangeSpec names refer to the same logical ChangeSpec.

    Returns True if names match exactly, or if stripping the _<N> suffix
    from either name yields the other. Handles the case where a ChangeSpec
    is renamed (e.g., suffix stripped on status change to Ready).
    """
    if name_a == name_b:
        return True
    return strip_reverted_suffix(name_a) == name_b or name_a == strip_reverted_suffix(name_b)
```

### Phase 2: Update `navigate_to_changespec_tab()` (`<enter>` keymap)

**File:** `src/sase/ace/tui/actions/agents/_notification_navigation.py`

Replace exact matches at lines 158 and 193:

- `cs.name == changespec_name` → `changespec_names_match(cs.name, changespec_name)`

### Phase 3: Update `_load_agents_for_cl()` (`L` keymap)

**File:** `src/sase/ace/tui/modals/agent_run_log_modal.py`

Replace exact matches:

- Line 52: `a.cl_name == cl_name` → `changespec_names_match(a.cl_name, cl_name)`
- Line 58: `cs_name == cl_name` → `changespec_names_match(cs_name, cl_name)`
- Line 78: both comparisons in the `!=` condition → negate `changespec_names_match`

### Phase 4: Tests

**File:** `tests/core/test_changespec_names_match.py` (new)

Unit tests for `changespec_names_match`:

- Exact match returns True
- Suffix on first arg matches base on second
- Suffix on second arg matches base on first
- Different bases with same suffix return False (`foo_1` vs `bar_1`)
- Two different suffixes on same base return False (`foo_1` vs `foo_2`)

**File:** `tests/ace/tui/test_jump_to_changespec.py` (extend)

- Test `navigate_to_changespec_tab` finds a ChangeSpec when agent has suffixed name but ChangeSpec was renamed
