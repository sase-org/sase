---
create_time: 2026-03-31 17:13:56
status: done
prompt: sdd/prompts/202603/bug_tag_sync.md
---

# Plan: Sync BUG tag to ChangeSpec BUG field

## Problem

When the user presses `W` on the CLs tab and adds a `BUG` tag, `add_tag_task` amends the git commit message with
`BUG=<value>` but does **not** update the `BUG:` field in the `.gp` ChangeSpec file. This means the TUI's BUG display
and any downstream consumers of the `.gp` file remain stale until a manual edit.

By contrast, `reword_execute_task` already syncs the DESCRIPTION field back via `_sync_description_bg()`.

## Design

The fix follows the established pattern for atomic field updates (CL, PARENT, DESCRIPTION all have `_apply_*_update` +
`update_changespec_*_atomic` pairs in `field_updates.py`).

## Phase 1: Add BUG field update to `field_updates.py`

Add two functions following the CL update pattern:

- **`_apply_bug_update(lines, changespec_name, new_bug)`** — Scans lines for the target ChangeSpec by NAME, then:
  - If `BUG:` line exists: replaces it (or removes it when `new_bug` is None)
  - If `BUG:` line is missing and `new_bug` is not None: inserts `BUG: <value>` before `STATUS:`
- **`update_changespec_bug_atomic(project_file, changespec_name, new_bug)`** — Acquires lock, reads file, applies
  update, writes atomically.

## Phase 2: Wire into `add_tag_task` in `reword.py`

After the successful `provider.reword_add_tag()` call (line ~239), add a check: if `tag_name.upper() == "BUG"`, call
`update_changespec_bug_atomic(changespec_file_path, changespec_name, tag_value)`.

## Phase 3: Tests

Add tests for `_apply_bug_update` covering:

- Update existing BUG field
- Insert BUG field when absent (before STATUS)
- Remove BUG field (new_bug=None)
- No-op when target ChangeSpec not found
