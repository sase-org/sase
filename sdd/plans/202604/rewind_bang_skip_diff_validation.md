---
create_time: 2026-04-15 13:50:25
status: done
prompt: sdd/prompts/202604/rewind_bang_skip_diff_validation.md
---

# Plan: Skip DIFF path validation when rewind `!` suffix is used

## Problem

The rewind `!` suffix (bookkeeping only mode) fails with "Entry (N) has no DIFF path" because the DIFF path validation
runs unconditionally before the `skip_vcs` early-return branch.

There are two validation sites:

1. `src/sase/ace/tui/actions/hints/_rewind.py` lines 128-137 — TUI action handler
2. `src/sase/workflows/rewind/workflow.py` lines 80-84 — workflow `run()` method

Both check `selected_entry.diff` before considering `skip_vcs`. In bookkeeping-only mode, no diffs are applied, so this
validation should be skipped.

## Changes

### Phase 1: Skip DIFF validation in TUI action when `skip_vcs`

**File: `src/sase/ace/tui/actions/hints/_rewind.py`**

Wrap the DIFF path validation (lines 128-137) in a `if not skip_vcs:` guard so it only runs when VCS operations will
actually be performed.

### Phase 2: Skip DIFF validation in workflow when `skip_vcs`

**File: `src/sase/workflows/rewind/workflow.py`**

Wrap the DIFF path validation (lines 80-84) in a `if not self._skip_vcs:` guard so it only runs when VCS operations will
actually be performed.
